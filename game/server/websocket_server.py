"""
WebSocket server for Kung-Fu Chess multiplayer.

Accepts client connections, authenticates via UserService,
and delegates gameplay to a GameSession.
"""

import asyncio
import logging

import websockets

from game.server.auth.user_service import UserService
from game.server.game_session import GameSession
from game.server.protocol import (
    decode_message,
    make_error,
    make_rating_updated,
    validate_login_request,
)
from game.server.rating.rating_service import RatingService

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765


class GameWebSocketServer:
    """
    Async WebSocket server. Authenticates clients via UserService,
    then routes gameplay messages through GameSession.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 session: GameSession | None = None,
                 user_service: UserService | None = None,
                 rating_service: RatingService | None = None):
        self.host = host
        self.port = port
        self.session = session or GameSession()
        self.user_service = user_service
        self.rating_service = rating_service
        self._server = None
        # Game ID derived from the session's engine identity — unique per engine object.
        # The current architecture supports one game per GameSession lifetime.
        self._game_id = f"game-{id(self.session.engine)}"

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

        # Map winner/loser colors to usernames
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

        # Queue rating_updated messages for broadcast
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
        logger.info(f"Server started on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Shut down the server and tick loop cleanly."""
        await self.session.stop_tick_loop()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Server stopped")

    async def _handle_client(self, websocket) -> None:
        """Handle a single client connection lifecycle."""
        remote = websocket.remote_address
        logger.info(f"Client connected: {remote}")

        # Register connection. No color assigned yet — client must authenticate.
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
                # Drain any queued broadcasts from engine events or accepted moves.
                await self.session.drain_outbox()
        except websockets.ConnectionClosed:
            logger.info(f"Client disconnected: {remote}")
        except Exception as e:
            logger.error(f"Error handling client {remote}: {e}")
        finally:
            self.session.remove_client(websocket)

    async def _route_message(self, raw: str, sender) -> str | list[str] | None:
        """
        Route a message: handle login_request at this layer (authentication),
        delegate everything else to GameSession.
        """
        msg = decode_message(raw)

        if msg is not None and msg.get("type") == "login_request":
            return self._handle_login_request(msg.get("payload", {}), sender)

        # All non-login messages go to GameSession
        return await self.session.handle_message(raw, sender=sender)

    def _handle_login_request(self, payload: dict, sender) -> str | list[str]:
        """
        Authenticate via UserService, then delegate player assignment to GameSession.

        GameSession never sees passwords — only the authenticated username.
        """
        # Validate message shape
        error = validate_login_request(payload)
        if error:
            return make_error(error, "invalid_login_request")

        action = payload["action"]
        username = payload["username"].strip()
        password = payload["password"]

        # If no UserService is configured, reject all logins
        if self.user_service is None:
            return make_error("authentication not available", "server_error")

        # Perform authentication or registration
        if action == "register":
            result = self.user_service.register(username, password)
        else:  # action == "login"
            result = self.user_service.authenticate(username, password)

        if not result.success:
            return make_error(
                result.error or "authentication failed",
                result.error or "invalid_credentials",
            )

        # Authentication succeeded — delegate to GameSession for player assignment
        # Use the canonical username from the database record
        canonical_username = result.user.username if result.user else username
        rating = result.user.rating if result.user else 1200
        messages = self.session.login_client(sender, canonical_username, rating=rating)
        if len(messages) == 1:
            return messages[0]
        return messages

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
