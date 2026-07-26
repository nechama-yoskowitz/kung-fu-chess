"""
WebSocket server for Kung-Fu Chess multiplayer.

Accepts client connections, authenticates via UserService,
manages matchmaking, creates GameSessions via GameSessionManager,
and routes gameplay messages to the correct session.
"""

import asyncio
import logging

import websockets

from game.model.constants import DEFAULT_RATING
from game.server.auth.user_service import UserService
from game.server.game_session import GameSession
from game.server.game_session_manager import GameSessionManager
from game.server.matchmaking.matchmaking_service import MatchmakingService
from game.server.protocol import (
    decode_message,
    make_error,
    make_match_found,
    make_matchmaking_cancelled,
    make_matchmaking_started,
    make_matchmaking_timeout,
    make_player_disconnected,
    make_player_reconnected,
    make_rating_updated,
    make_reconnect_countdown,
    make_room_created,
    make_room_joined,
    validate_login_request,
)
from game.server.rating.rating_service import RatingService
from game.server.reconnect_manager import ReconnectManager, RECONNECT_TIMEOUT
from game.server.room_manager import RoomManager

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765

MATCHMAKING_POLL_INTERVAL = 0.5  # seconds


class GameWebSocketServer:
    """
    Async WebSocket server. Authenticates clients via UserService,
    manages matchmaking, creates game sessions via GameSessionManager,
    and routes gameplay messages to the correct session per client.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 session: GameSession | None = None,
                 user_service: UserService | None = None,
                 rating_service: RatingService | None = None,
                 matchmaking: MatchmakingService | None = None,
                 session_manager: GameSessionManager | None = None,
                 reconnect_manager: ReconnectManager | None = None):
        self.host = host
        self.port = port
        self.user_service = user_service
        self.rating_service = rating_service
        self.matchmaking = matchmaking or MatchmakingService()
        self.session_manager = session_manager or GameSessionManager()
        self.room_manager = RoomManager(self.session_manager)
        self.reconnect_manager = reconnect_manager or ReconnectManager()
        self._server = None
        # Tracks authenticated clients: websocket → {"username": str, "rating": int}
        self._authenticated: dict = {}
        # All connected websockets (for lifecycle management)
        self._connected: set = set()
        # Matchmaking poll task
        self._matchmaking_task: asyncio.Task | None = None
        # Reconnect poll task
        self._reconnect_task: asyncio.Task | None = None

        # Backward compatibility: if a pre-built session is provided,
        # register it in the manager (supports existing tests).
        if session is not None:
            self.session = session
            self.session_manager.register_session(session)
        else:
            self.session = None

    async def start(self) -> None:
        """Start the server and the matchmaking loop."""
        self._server = await websockets.serve(
            self._handle_client, self.host, self.port
        )
        # Start tick loops for any pre-registered sessions
        for session in self.session_manager.iter_sessions():
            await session.start_tick_loop()
        self._matchmaking_task = asyncio.create_task(self._matchmaking_loop())
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        logger.info(f"Server started on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Shut down the server cleanly."""
        if self._matchmaking_task:
            self._matchmaking_task.cancel()
            try:
                await self._matchmaking_task
            except asyncio.CancelledError:
                pass
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        # Stop all active session tick loops
        for session in list(self.session_manager.iter_sessions()):
            await session.stop_tick_loop()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Server stopped")

    async def _handle_client(self, websocket) -> None:
        """Handle a single client connection lifecycle."""
        remote = websocket.remote_address
        logger.info(f"Client connected: {remote}")
        self._connected.add(websocket)

        try:
            async for message in websocket:
                response = await self._route_message(message, websocket)
                if response is not None:
                    if isinstance(response, list):
                        for msg in response:
                            await websocket.send(msg)
                    else:
                        await websocket.send(response)
                # Drain outbox for the client's session if they have one
                session = self.session_manager.get_session_for_client(websocket)
                if session:
                    await session.drain_outbox()
        except websockets.ConnectionClosed:
            logger.info(f"Client disconnected: {remote}")
        except Exception as e:
            logger.error(f"Error handling client {remote}: {e}")
        finally:
            self._cleanup_client(websocket)

    def _cleanup_client(self, websocket) -> None:
        """Handle client disconnect — start reconnect for players, clean up viewers."""
        self._connected.discard(websocket)
        self.matchmaking.remove_by_websocket(websocket)
        auth = self._authenticated.pop(websocket, None)

        # Check if this was an active player in a game session (not a viewer)
        # Only start reconnect if the game has actually started (2 players present)
        session = self.session_manager.get_session_for_client(websocket)
        if (session and not session.is_viewer(websocket)
                and not session.engine.game_over
                and session.player_count >= 2):
            color = session.get_player_color(websocket)
            username = session.get_player_username(websocket) or (auth["username"] if auth else None)
            session_id = self.session_manager.get_session_id(session)
            room = self.room_manager.get_room_for_client(websocket)
            room_id = room.room_id if room else None

            if username and color and session_id:
                # Start reconnect reservation
                self.reconnect_manager.start_reconnect(
                    username=username,
                    color=color,
                    room_id=room_id,
                    session_id=session_id,
                )
                logger.info(f"Reconnect reservation: username={username} color={color} session={session_id}")
                # Notify remaining session members
                msg = make_player_disconnected(username, color, int(RECONNECT_TIMEOUT))
                session.queue_broadcast(msg)
                # Remove websocket routing but keep the session/room slot reserved
                self.session_manager.remove_client(websocket)
                return

        # Viewer or no active game — normal cleanup
        self.room_manager.remove_client(websocket)
        if session:
            session.remove_client(websocket)
        self.session_manager.remove_client(websocket)

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

            if msg_type == "create_room":
                return await self._handle_create_room(sender)

            if msg_type == "join_room":
                return await self._handle_join_room(msg.get("payload", {}), sender)

            if msg_type == "leave_room":
                return self._handle_leave_room(sender)

        # Gameplay messages go to the client's assigned session
        session = self.session_manager.get_session_for_client(sender)
        if session:
            return await session.handle_message(raw, sender=sender)

        # Backward compat: if a single session exists and client is registered there
        if self.session is not None:
            return await self.session.handle_message(raw, sender=sender)

        return make_error("not in a game session", "no_session")

    def _handle_login_request(self, payload: dict, sender) -> str | list[str]:
        """Authenticate via UserService."""
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
            logger.warning(f"Login failed: username={username} action={action} error={result.error}")
            return make_error(
                result.error or "authentication failed",
                result.error or "invalid_credentials",
            )

        canonical_username = result.user.username if result.user else username
        rating = result.user.rating if result.user else DEFAULT_RATING
        logger.info(f"Login success: username={canonical_username} action={action} rating={rating}")

        # Track authenticated state
        self._authenticated[sender] = {
            "username": canonical_username,
            "rating": rating,
        }

        # Check for pending reconnect
        pending = self.reconnect_manager.try_reconnect(canonical_username)
        if pending:
            return self._handle_reconnect(sender, pending, canonical_username, rating)

        # If there's a legacy single session, assign directly (backward compat for tests)
        if self.session is not None:
            messages = self.session.login_client(sender, canonical_username, rating=rating)
            self.session_manager.assign_client_to_session(sender, self.session)
            if len(messages) == 1:
                return messages[0]
            return messages

        # Otherwise, client is authenticated but not yet in a game.
        # They should use play_request to enter matchmaking.
        from game.server.protocol import make_login_success
        return make_login_success(username=canonical_username, color="", rating=rating)

    def _handle_reconnect(self, websocket, pending, username: str, rating: int) -> str | list[str]:
        """Restore a reconnecting player to their original session and color."""
        session = self.session_manager.get_session_by_id(pending.session_id)
        if session is None or session.engine.game_over:
            self.reconnect_manager.cancel(username)
            logger.warning(f"Reconnect failed: username={username} reason=game_no_longer_available")
            return make_error("game no longer available", "reconnect_failed")

        # Cancel the reconnect timer
        self.reconnect_manager.cancel(username)
        logger.info(f"Reconnect success: username={username} color={pending.color} session={pending.session_id}")

        # Re-register in the session with the original color
        session.restore_player(websocket, pending.color, username)

        # Restore session manager routing
        self.session_manager.assign_client_to_session(websocket, session)

        # Restore room membership if applicable
        if pending.room_id:
            room = self.room_manager.get_room(pending.room_id)
            if room and websocket not in room.players:
                room.players.append(websocket)

        # Notify other players/viewers
        msg = make_player_reconnected(username, pending.color)
        session.queue_broadcast(msg)

        # Send current game state to the reconnected player
        from game.server.protocol import make_game_state, make_login_success
        messages = [
            make_login_success(username=username, color=pending.color, rating=rating, reconnected=True),
            make_game_state(
                board=session.engine.legacy_board,
                clock=session.engine.clock,
                white_score=session.engine.white_score,
                black_score=session.engine.black_score,
                game_over=session.engine.game_over,
            ),
        ]
        return messages

    async def _handle_play_request(self, sender) -> str:
        """Add authenticated player to matchmaking queue."""
        auth = self._authenticated.get(sender)
        if auth is None:
            return make_error("must login first", "not_logged_in")

        # Don't allow if already in a game
        if self.session_manager.is_client_in_session(sender):
            return make_error("already in a game", "already_in_game")

        added = self.matchmaking.enqueue(
            websocket=sender,
            username=auth["username"],
            rating=auth["rating"],
        )

        if not added:
            return make_error("already in matchmaking queue", "already_queued")

        logger.info(f"Matchmaking: {auth['username']} entered queue (rating={auth['rating']})")
        return make_matchmaking_started()

    def _handle_cancel_matchmaking(self, sender) -> str:
        """Remove from matchmaking queue."""
        removed = self.matchmaking.cancel(sender)
        if removed:
            return make_matchmaking_cancelled()
        return make_error("not in matchmaking queue", "not_queued")

    async def _handle_create_room(self, sender) -> str:
        """Create a new room and assign the creator as White."""
        auth = self._authenticated.get(sender)
        if auth is None:
            return make_error("must login first", "not_logged_in")

        room = self.room_manager.create_room()
        error, role = self.room_manager.join_room(
            room.room_id, sender, auth["username"], auth["rating"]
        )
        if error:
            return make_error(error, error)

        await room.session.start_tick_loop()
        logger.info(f"Room created: room_id={room.room_id} creator={auth['username']}")
        return make_room_created(room.room_id)

    async def _handle_join_room(self, payload: dict, sender) -> str | list[str]:
        """Join an existing room by ID as player or viewer."""
        auth = self._authenticated.get(sender)
        if auth is None:
            return make_error("must login first", "not_logged_in")

        room_id = payload.get("room_id", "")
        if not room_id:
            return make_error("missing room_id", "invalid_request")

        error, role = self.room_manager.join_room(
            room_id, sender, auth["username"], auth["rating"]
        )
        if error == "room_not_found":
            return make_error("room not found", "room_not_found")

        room = self.room_manager.get_room(room_id)
        color = room.session.get_player_color(sender) if role == "player" else None

        # Send room_joined to the joiner
        messages = [make_room_joined(room_id, color, role)]

        # When the second player joins (room now full), broadcast game_state to ALL
        if role == "player" and room.is_full:
            from game.server.protocol import make_game_state
            game_state_msg = make_game_state(
                board=room.session.engine.legacy_board,
                clock=room.session.engine.clock,
                white_score=room.session.engine.white_score,
                black_score=room.session.engine.black_score,
                game_over=room.session.engine.game_over,
            )
            # Queue broadcast to all session members (including Player 1)
            room.session.queue_broadcast(game_state_msg)

        # Viewers get immediate game_state in their response
        if role == "viewer":
            from game.server.protocol import make_game_state
            messages.append(make_game_state(
                board=room.session.engine.legacy_board,
                clock=room.session.engine.clock,
                white_score=room.session.engine.white_score,
                black_score=room.session.engine.black_score,
                game_over=room.session.engine.game_over,
            ))

        return messages

    def _handle_leave_room(self, sender) -> str:
        """Handle leave_room: remove player from their room."""
        room = self.room_manager.get_room_for_client(sender)
        if room is None:
            return make_error("not in a room", "not_in_room")

        self.room_manager.remove_client(sender)
        session = self.session_manager.get_session_for_client(sender)
        if session:
            session.remove_client(sender)
        self.session_manager.remove_client(sender)

        from game.server.protocol import encode_message
        return encode_message("room_left", {})

    async def _matchmaking_loop(self) -> None:
        """Periodically check for matches and timeouts."""
        while True:
            await asyncio.sleep(MATCHMAKING_POLL_INTERVAL)
            await self._process_matchmaking()

    async def _process_matchmaking(self) -> None:
        """Check for timeouts and matches, create sessions for matched players."""
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
        logger.info(f"Match found: {p1.username} ({p1.rating}) vs {p2.username} ({p2.rating})")

        # Create a new GameSession for the matched players
        session = self.session_manager.create_session()
        await session.start_tick_loop()

        # Register players in the session
        session.add_client(p1.websocket)
        session.add_client(p2.websocket)
        session.login_client(p1.websocket, p1.username, rating=p1.rating)
        session.login_client(p2.websocket, p2.username, rating=p2.rating)

        # Map websockets to this session
        self.session_manager.assign_client_to_session(p1.websocket, session)
        self.session_manager.assign_client_to_session(p2.websocket, session)

        # Subscribe to GameEnded for rating updates
        if self.rating_service:
            session_id = self.session_manager.get_session_id(session)
            self._subscribe_rating_updates(session, session_id)

        # Send match_found to both players (player1=White, player2=Black)
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

        # Broadcast initial game_state to both players so clients can start
        from game.server.protocol import make_game_state
        game_state_msg = make_game_state(
            board=session.engine.legacy_board,
            clock=session.engine.clock,
            white_score=session.engine.white_score,
            black_score=session.engine.black_score,
            game_over=session.engine.game_over,
        )
        session.queue_broadcast(game_state_msg)
        await session.drain_outbox()

    def _subscribe_rating_updates(self, session: GameSession, session_id: str) -> None:
        """Subscribe to GameEnded on a session's engine for rating updates."""
        from game.events.engine_events import GameEnded

        def on_game_ended(event):
            if self.rating_service is None:
                return

            winner_color = "w" if event.winner == "w" else "b"
            loser_color = "b" if winner_color == "w" else "w"

            winner_username = session.get_username_for_color(winner_color)
            loser_username = session.get_username_for_color(loser_color)

            if not winner_username or not loser_username:
                return

            result = self.rating_service.process_game_end(
                game_id=session_id,
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

            session.queue_broadcast(winner_msg)
            session.queue_broadcast(loser_msg)

        session.engine.event_bus.subscribe(GameEnded, on_game_ended)

    async def _reconnect_loop(self) -> None:
        """Periodically check for expired reconnect deadlines and trigger auto-resign."""
        while True:
            await asyncio.sleep(1.0)
            await self._process_reconnect_expirations()

    async def _process_reconnect_expirations(self) -> None:
        """Handle expired reconnect records — auto-resign the disconnected player."""
        expired = self.reconnect_manager.get_expired()
        for record in expired:
            logger.warning(f"Reconnect timeout: username={record.username} color={record.color} session={record.session_id}")
            session = self.session_manager.get_session_by_id(record.session_id)
            if session is None or session.engine.game_over:
                continue

            # Determine winner (the opponent still connected)
            winner_color = "b" if record.color == "w" else "w"
            loser_color = record.color

            # End the game authoritatively
            from game.server.protocol import make_game_ended
            msg = make_game_ended(winner=winner_color, loser=loser_color)
            session.engine.game_over = True
            session.queue_broadcast(msg)

            # Update ratings via RatingService
            if self.rating_service:
                winner_username = session.get_username_for_color(winner_color)
                if winner_username:
                    self.rating_service.process_game_end(
                        game_id=record.session_id,
                        winner_username=winner_username,
                        loser_username=record.username,
                    )

            # Drain broadcasts to connected clients
            await session.drain_outbox()

    @property
    def client_count(self) -> int:
        return len(self._connected)


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
