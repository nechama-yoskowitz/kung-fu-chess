"""
Application-level routing for WebSocket clients.

Orchestrates authentication, matchmaking, rooms, reconnection, and
session assignment. Does not know about raw WebSocket frames or transport.

Collaborates with:
- UserService for credential verification
- GameSessionManager for session registry
- RoomManager for room membership
- ReconnectManager for disconnect/reconnect flow
- MatchmakingService for queue management
- RatingService for post-game ELO updates
- GameSession for gameplay message delegation
"""

import logging
from typing import Callable, Awaitable

from game.model.constants import DEFAULT_RATING
from game.server.auth.user_service import UserService
from game.server.game_session import GameSession
from game.server.game_session_manager import GameSessionManager
from game.server.matchmaking.matchmaking_service import MatchmakingService
from game.server.protocol import (
    decode_message,
    encode_message,
    make_error,
    make_game_ended,
    make_game_state,
    make_login_success,
    make_match_found,
    make_matchmaking_cancelled,
    make_matchmaking_started,
    make_matchmaking_timeout,
    make_player_disconnected,
    make_player_reconnected,
    make_rating_updated,
    make_room_created,
    make_room_joined,
    validate_login_request,
)
from game.server.rating.rating_service import RatingService
from game.server.reconnect_manager import ReconnectManager, RECONNECT_TIMEOUT
from game.server.room_manager import RoomManager

logger = logging.getLogger(__name__)


# Type alias: async function that sends a message to a specific client.
SendFunc = Callable[[object, str], Awaitable[None]]


class ClientSessionRouter:
    """
    Application-layer coordinator for multiplayer game connections.

    Handles login, reconnect, matchmaking, rooms, and session routing.
    Returns outbound messages to the caller (transport layer) rather than
    sending directly over WebSocket.
    """

    def __init__(
        self,
        user_service: UserService | None = None,
        rating_service: RatingService | None = None,
        matchmaking: MatchmakingService | None = None,
        session_manager: GameSessionManager | None = None,
        reconnect_manager: ReconnectManager | None = None,
        room_manager: RoomManager | None = None,
        *,
        legacy_session: GameSession | None = None,
    ):
        self.user_service = user_service
        self.rating_service = rating_service
        self.matchmaking = matchmaking or MatchmakingService()
        self.session_manager = session_manager or GameSessionManager()
        self.room_manager = room_manager or RoomManager(self.session_manager)
        self.reconnect_manager = reconnect_manager or ReconnectManager()

        # Tracks authenticated clients: websocket → {"username": str, "rating": int}
        self._authenticated: dict = {}

        # Backward compatibility: legacy single-session mode for tests.
        self.legacy_session = legacy_session
        if legacy_session is not None:
            self.session_manager.register_session(legacy_session)

    # ─── Main entry points (called by transport) ──────────────────────────

    async def route_message(self, raw: str, sender) -> str | list[str] | None:
        """
        Route a decoded protocol message to the appropriate handler.

        Returns outbound message(s) to send to the sender, or None if
        only broadcasts were queued on the session.
        """
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

        # Backward compat: legacy single session
        if self.legacy_session is not None:
            return await self.legacy_session.handle_message(raw, sender=sender)

        return make_error("not in a game session", "no_session")

    def on_disconnect(self, websocket) -> None:
        """
        Handle client disconnect — start reconnect for players, clean up viewers.

        Called by the transport layer when a connection closes.
        """
        self.matchmaking.remove_by_websocket(websocket)
        auth = self._authenticated.pop(websocket, None)

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
                self.reconnect_manager.start_reconnect(
                    username=username,
                    color=color,
                    room_id=room_id,
                    session_id=session_id,
                )
                logger.info(f"Reconnect reservation: username={username} color={color} session={session_id}")
                msg = make_player_disconnected(username, color, int(RECONNECT_TIMEOUT))
                session.queue_broadcast(msg)
                self.session_manager.remove_client(websocket)
                return

        # Viewer or no active game — normal cleanup
        self.room_manager.remove_client(websocket)
        if session:
            session.remove_client(websocket)
        self.session_manager.remove_client(websocket)

    # ─── Periodic processing (called by transport tick loops) ─────────────

    async def process_matchmaking(self, send: SendFunc) -> None:
        """Check for matches and timeouts. Uses send callback for direct messages."""
        timed_out = self.matchmaking.get_timed_out()
        for entry in timed_out:
            try:
                await send(entry.websocket, make_matchmaking_timeout())
            except Exception:
                pass

        match = self.matchmaking.try_match()
        if match is None:
            return

        p1, p2 = match.player1, match.player2
        logger.info(f"Match found: {p1.username} ({p1.rating}) vs {p2.username} ({p2.rating})")

        session = self.session_manager.create_session()
        await session.start_tick_loop()

        session.add_client(p1.websocket)
        session.add_client(p2.websocket)
        session.login_client(p1.websocket, p1.username, rating=p1.rating)
        session.login_client(p2.websocket, p2.username, rating=p2.rating)

        self.session_manager.assign_client_to_session(p1.websocket, session)
        self.session_manager.assign_client_to_session(p2.websocket, session)

        if self.rating_service:
            session_id = self.session_manager.get_session_id(session)
            self._subscribe_rating_updates(session, session_id)

        msg1 = make_match_found(
            opponent_username=p2.username, color="w",
            own_rating=p1.rating, opponent_rating=p2.rating,
        )
        msg2 = make_match_found(
            opponent_username=p1.username, color="b",
            own_rating=p2.rating, opponent_rating=p1.rating,
        )

        try:
            await send(p1.websocket, msg1)
        except Exception:
            pass
        try:
            await send(p2.websocket, msg2)
        except Exception:
            pass

        game_state_msg = make_game_state(
            board=session.engine.legacy_board,
            clock=session.engine.clock,
            white_score=session.engine.white_score,
            black_score=session.engine.black_score,
            game_over=session.engine.game_over,
        )
        session.queue_broadcast(game_state_msg)
        await session.drain_outbox()

    async def process_reconnect_expirations(self) -> None:
        """Handle expired reconnect records — auto-resign the disconnected player."""
        expired = self.reconnect_manager.get_expired()
        for record in expired:
            logger.warning(f"Reconnect timeout: username={record.username} color={record.color} session={record.session_id}")
            session = self.session_manager.get_session_by_id(record.session_id)
            if session is None or session.engine.game_over:
                continue

            winner_color = "b" if record.color == "w" else "w"
            loser_color = record.color

            msg = make_game_ended(winner=winner_color, loser=loser_color)
            session.engine.game_over = True
            session.queue_broadcast(msg)

            if self.rating_service:
                winner_username = session.get_username_for_color(winner_color)
                if winner_username:
                    self.rating_service.process_game_end(
                        game_id=record.session_id,
                        winner_username=winner_username,
                        loser_username=record.username,
                    )

            await session.drain_outbox()

    # ─── Private handlers ─────────────────────────────────────────────────

    def _handle_login_request(self, payload: dict, sender) -> str | list[str]:
        """Authenticate via UserService and route to session or matchmaking."""
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

        self._authenticated[sender] = {
            "username": canonical_username,
            "rating": rating,
        }

        # Check for pending reconnect
        pending = self.reconnect_manager.try_reconnect(canonical_username)
        if pending:
            return self._handle_reconnect(sender, pending, canonical_username, rating)

        # Legacy single-session mode
        if self.legacy_session is not None:
            messages = self.legacy_session.login_client(sender, canonical_username, rating=rating)
            self.session_manager.assign_client_to_session(sender, self.legacy_session)
            if len(messages) == 1:
                return messages[0]
            return messages

        return make_login_success(username=canonical_username, color="", rating=rating)

    def _handle_reconnect(self, websocket, pending, username: str, rating: int) -> str | list[str]:
        """Restore a reconnecting player to their original session."""
        session = self.session_manager.get_session_by_id(pending.session_id)
        if session is None or session.engine.game_over:
            self.reconnect_manager.cancel(username)
            logger.warning(f"Reconnect failed: username={username} reason=game_no_longer_available")
            return make_error("game no longer available", "reconnect_failed")

        self.reconnect_manager.cancel(username)
        logger.info(f"Reconnect success: username={username} color={pending.color} session={pending.session_id}")

        session.restore_player(websocket, pending.color, username)
        self.session_manager.assign_client_to_session(websocket, session)

        if pending.room_id:
            room = self.room_manager.get_room(pending.room_id)
            if room and websocket not in room.players:
                room.players.append(websocket)

        msg = make_player_reconnected(username, pending.color)
        session.queue_broadcast(msg)

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

        if self.session_manager.is_client_in_session(sender):
            return make_error("already in a game", "already_in_game")

        added = self.matchmaking.enqueue(
            websocket=sender, username=auth["username"], rating=auth["rating"],
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
        """Create a new room and assign the creator."""
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
        """Join an existing room by ID."""
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

        messages = [make_room_joined(room_id, color, role)]

        if role == "player" and room.is_full:
            game_state_msg = make_game_state(
                board=room.session.engine.legacy_board,
                clock=room.session.engine.clock,
                white_score=room.session.engine.white_score,
                black_score=room.session.engine.black_score,
                game_over=room.session.engine.game_over,
            )
            room.session.queue_broadcast(game_state_msg)

        if role == "viewer":
            messages.append(make_game_state(
                board=room.session.engine.legacy_board,
                clock=room.session.engine.clock,
                white_score=room.session.engine.white_score,
                black_score=room.session.engine.black_score,
                game_over=room.session.engine.game_over,
            ))

        return messages

    def _handle_leave_room(self, sender) -> str:
        """Remove player from their room."""
        room = self.room_manager.get_room_for_client(sender)
        if room is None:
            return make_error("not in a room", "not_in_room")

        self.room_manager.remove_client(sender)
        session = self.session_manager.get_session_for_client(sender)
        if session:
            session.remove_client(sender)
        self.session_manager.remove_client(sender)

        return encode_message("room_left", {})

    def _subscribe_rating_updates(self, session: GameSession, session_id: str) -> None:
        """Subscribe to GameEnded for ELO updates on a session."""
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

            session.queue_broadcast(make_rating_updated(
                username=result.winner.username,
                old_rating=result.winner.old_rating,
                new_rating=result.winner.new_rating,
                change=result.winner.change,
            ))
            session.queue_broadcast(make_rating_updated(
                username=result.loser.username,
                old_rating=result.loser.old_rating,
                new_rating=result.loser.new_rating,
                change=result.loser.change,
            ))

        session.engine.event_bus.subscribe(GameEnded, on_game_ended)
