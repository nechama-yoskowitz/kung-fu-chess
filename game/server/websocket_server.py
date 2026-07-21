"""
WebSocket server for Kung-Fu Chess multiplayer.

Accepts client connections, authenticates via UserService,
manages matchmaking, and delegates gameplay to GameSessions.
"""

import asyncio
import logging

import websockets

from game.server.auth.user_service import UserService
from game.server.game_session import GameSession
from game.server.matchmaking.matchmaking_service import MatchmakingService
from game.server.protocol import (
    decode_message,
    make_error,
    make_match_found,
    make_matchmaking_cancelled,
    make_matchmaking_started,
    make_matchmaking_timeout,
    make_rating_updated,
    validate_login_request,
)
from game.server.rating.rating_service import RatingService

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765

MATCHMAKING_POLL_INTERVAL = 0.5  # seconds


class GameWebSocketServer:
    """
    Async WebSocket server. Authenticates clients via UserService,
    manages matchmaking, then routes gameplay messages through GameSession.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 session: GameSession | None = None,
                 user_service: UserService | None = None,
                 rating_service: RatingService | None = None,
                 matchmaking: MatchmakingService | None = None):
        self.host = host
        self.port = port
        self.session = session or GameSession()
        self.user_service = user_service
        self.rating_service = rating_service
        self.matchmaking = matchmaking or MatchmakingService()
        self._server = None
        # Tracks authenticated clients: websocket → {"username": str, "rating": int}
        self._authenticated: dict = {}
        # Game ID derived from the session's engine identity.
        self._game_id = f"game-{id(self.session.engine)}"
        # Matchmaking poll task
        self._matchmaking_task: asyncio.Task | None = None

        # Subscribe to GameEnded for rating updates
        if self.rating_service:
            from game.events.engine_events import GameEnded
            self.session.engine.event_bus.subscribe(
                GameEnded, self._on_game_ended_for_rating
            )

    def _on_game_ended_for_rating(self, event) -> None:
        """
        React to GameEnded by computing and broadcasting rating updates.

        This runs synchronously inside the engine's EventBus dispatch
        (during tick), so we queue messages into the session outbox.
        """
        if self.rating_service is None:
            return

        winner_username = None
        loser_username = None

        for ws, color in self.session._player_colors.items():
            username = self.session._player_usernames.get(ws)
            if color == event.winner:
                winner_username = username
            elif color == event.loser:
                loser_username = username

        if not winner_username or not loser_username:
            logger.warning("Rating update skipped: could not resolve both player usernames")
            return

        result = self.rating_service.process_game_end(
            game_id=self._game_id,
            winner_username=winner_username,
            loser_username=loser_username,
        )

        if result is None:
            return

        winner_msg = make_rating_updated(
            username=result.winner.username,
            old_rating=result.winner.old_rating,
            new_rating=result.winner.new_rating,
            change=result.winner.change,
        )
        loser_msg = make_rating_updated(
            username=result.loser.username,
            old_rating=result.loser.old_rating,
            new_rating=result.loser.new_rating,
            change=result.loser.change,
        )

        self.session._queue_broadcast(winner_msg)
        self.session._queue_broadcast(loser_msg)

    async def start(self) -> None:
        """Start the server and the game tick loop."""
        self._server = await websockets.serve(
            self._handle_client, self.host, self.port
        )
        await self.session.start_tick_loop()
        self._matchmaking_task = asyncio.create_task(self._matchmaking_loop())
        logger.info(f"Server started on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Shut down the server and tick loop cleanly."""
        if self._matchmaking_task:
            self._matchmaking_task.cancel()
            try:
                await self._matchmaking_task
            except asyncio.CancelledError:
                pass
        await self.session.stop_tick_loop()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Server stopped")

    async def _handle_client(self, websocket) -> None:
        """Handle a single client connection lifecycle."""
        remote = websocket.remote_address
        logger.info(f"Client connected: {remote}")

        self.session.add_client(websocket)

        try:
            async for message in websocket:
                response = await self._route_message(message, websocket)
                if response is not None:
                    if isinstance(response, list):
                        for msg in response:
                            await websocket.send(msg)
                    else:
                        await websocket.send(response)
                await self.session.drain_outbox()
        except websockets.ConnectionClosed:
            logger.info(f"Client disconnected: {remote}")
        except Exception as e:
            logger.error(f"Error handling client {remote}: {e}")
        finally:
            self.session.remove_client(websocket)
            self.matchmaking.remove_by_websocket(websocket)
            self._authenticated.pop(websocket, None)

    async def _route_message(self, raw: str, sender) -> str | list[str] | None:
        """Route messages to the appropriate handler."""
        msg = decode_message(raw)

        if msg is not None:
            msg_type = msg.get("type", "")

            if msg_type == "login_request":
                return self._handle_login_request(msg.get("payload", {}), sender)

            if msg_type == "play_request":
                return await self._handle_play_request(sender)

            if msg_type == "cancel_matchmaking":
                return self._handle_cancel_matchmaking(sender)

        # All other messages go to GameSession
        return await self.session.handle_message(raw, sender=sender)

    def _handle_login_request(self, payload: dict, sender) -> str | list[str]:
        """Authenticate via UserService, then assign player to the session."""
        error = validate_login_request(payload)
        if error:
            return make_error(error, "invalid_login_request")

        action = payload["action"]
        username = payload["username"].strip()
        password = payload["password"]

        if self.user_service is None:
            return make_error("authentication not available", "server_error")

        if action == "register":
            result = self.user_service.register(username, password)
        else:
            result = self.user_service.authenticate(username, password)

        if not result.success:
            return make_error(
                result.error or "authentication failed",
                result.error or "invalid_credentials",
            )

        canonical_username = result.user.username if result.user else username
        rating = result.user.rating if result.user else 1200

        # Track authenticated state
        self._authenticated[sender] = {
            "username": canonical_username,
            "rating": rating,
        }

        # Assign to the current game session
        messages = self.session.login_client(sender, canonical_username, rating=rating)
        if len(messages) == 1:
            return messages[0]
        return messages

    async def _handle_play_request(self, sender) -> str:
        """Handle a play_request: add authenticated player to matchmaking queue."""
        auth = self._authenticated.get(sender)
        if auth is None:
            return make_error("must login first", "not_logged_in")

        added = self.matchmaking.enqueue(
            websocket=sender,
            username=auth["username"],
            rating=auth["rating"],
        )

        if not added:
            return make_error("already in matchmaking queue", "already_queued")

        return make_matchmaking_started()

    def _handle_cancel_matchmaking(self, sender) -> str:
        """Handle cancel_matchmaking: remove from queue."""
        removed = self.matchmaking.cancel(sender)
        if removed:
            return make_matchmaking_cancelled()
        return make_error("not in matchmaking queue", "not_queued")

    async def _matchmaking_loop(self) -> None:
        """Periodically check for matches and timeouts."""
        while True:
            await asyncio.sleep(MATCHMAKING_POLL_INTERVAL)
            await self._process_matchmaking()

    async def _process_matchmaking(self) -> None:
        """Check for timeouts and matches, send appropriate messages."""
        # Handle timeouts
        timed_out = self.matchmaking.get_timed_out()
        for entry in timed_out:
            try:
                await entry.websocket.send(make_matchmaking_timeout())
            except Exception:
                pass

        # Try to find a match
        match = self.matchmaking.try_match()
        if match is None:
            return

        p1, p2 = match.player1, match.player2

        # Send match_found to both players
        # player1 gets White, player2 gets Black
        msg1 = make_match_found(
            opponent_username=p2.username,
            color="w",
            own_rating=p1.rating,
            opponent_rating=p2.rating,
        )
        msg2 = make_match_found(
            opponent_username=p1.username,
            color="b",
            own_rating=p2.rating,
            opponent_rating=p1.rating,
        )

        try:
            await p1.websocket.send(msg1)
        except Exception:
            pass
        try:
            await p2.websocket.send(msg2)
        except Exception:
            pass

    @property
    def client_count(self) -> int:
        return self.session.client_count


async def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                     user_service: UserService | None = None,
                     rating_service: RatingService | None = None) -> None:
    """Run the server until interrupted."""
    server = GameWebSocketServer(
        host=host, port=port,
        user_service=user_service,
        rating_service=rating_service,
    )
    await server.start()

    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
