"""
Application-level routing for WebSocket clients.

Orchestrates authentication, matchmaking, rooms, reconnection, and
session assignment. Does not know about raw WebSocket frames or transport.

Stage 2 change: matchmaking queue metadata, reconnect slots, and room/player
routing metadata are stored in a RedisStore (or NullRedisStore for tests).
Live game state (GameSession/GameEngine) remains in-process.
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
from game.server.reconnect_manager import RECONNECT_TIMEOUT
from game.server.redis_store import NullRedisStore
from game.server.room_manager import RoomManager

logger = logging.getLogger(__name__)

SendFunc = Callable[[object, str], Awaitable[None]]


class ClientSessionRouter:
    """
    Application-layer coordinator for multiplayer game connections.

    Stage 2: matchmaking queue entries, reconnect metadata, and room/player
    routing pointers are now stored in a shared store (RedisStore in production,
    NullRedisStore in tests). Live game state remains local.
    """

    def __init__(
        self,
        user_service: UserService | None = None,
        rating_service: RatingService | None = None,
        matchmaking: MatchmakingService | None = None,   # kept for compat
        session_manager: GameSessionManager | None = None,
        reconnect_manager=None,                           # kept for compat; ignored if store present
        room_manager: RoomManager | None = None,
        *,
        legacy_session: GameSession | None = None,
        store=None,          # RedisStore or NullRedisStore
    ):
        self.user_service = user_service
        self.rating_service = rating_service
        self.session_manager = session_manager or GameSessionManager()
        self.room_manager = room_manager or RoomManager(self.session_manager)

        # shared store: defaults to NullRedisStore (in-process, no Redis)
        self._store = store or NullRedisStore()

        # Keep the old in-memory MatchmakingService for backward-compat with
        # tests that inject it directly.  Its queue_size / is_queued attributes
        # are proxied from the store.
        self._local_mm = matchmaking or MatchmakingService()

        # ReconnectManager is kept for test compatibility.
        # Production code uses the store instead.
        if reconnect_manager is not None:
            self._reconnect_manager = reconnect_manager
            self._use_local_reconnect = True
        else:
            self._reconnect_manager = None
            self._use_local_reconnect = False

        # Tracks authenticated clients: websocket → {"username": str, "rating": int}
        self._authenticated: dict = {}

        # websocket → username (needed for matchmaking cancel on disconnect)
        self._ws_username: dict = {}

        # Backward compatibility: legacy single-session mode for tests.
        self.legacy_session = legacy_session
        if legacy_session is not None:
            self.session_manager.register_session(legacy_session)

    # ─── Backward-compat shim used by test_matchmaking.py ─────────────────
    # Tests access srv.matchmaking.queue_size — expose via a thin adapter.

    @property
    def matchmaking(self):
        """Backward-compat shim: expose queue_size/is_queued via the store."""
        return _MatchmakingShim(self._store, self._local_mm)

    # ─── Backward-compat shim used by test_reconnect.py ──────────────────

    @property
    def reconnect_manager(self):
        """Return the local reconnect manager (used by tests that inject one)."""
        return self._reconnect_manager

    # ─── Main entry points ─────────────────────────────────────────────────

    async def route_message(self, raw: str, sender) -> str | list[str] | None:
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

        session = self.session_manager.get_session_for_client(sender)
        if session:
            return await session.handle_message(raw, sender=sender)

        if self.legacy_session is not None:
            return await self.legacy_session.handle_message(raw, sender=sender)

        return make_error("not in a game session", "no_session")

    def on_disconnect(self, websocket) -> None:
        """Handle client disconnect."""
        username = self._ws_username.pop(websocket, None)
        if username:
            # Remove from shared matchmaking queue
            self._store.matchmaking_remove(username)
        # Also remove from local queue (covers tests that use local mm)
        self._local_mm.remove_by_websocket(websocket)

        auth = self._authenticated.pop(websocket, None)

        session = self.session_manager.get_session_for_client(websocket)
        if (session and not session.is_viewer(websocket)
                and not session.engine.game_over
                and session.player_count >= 2):
            color = session.get_player_color(websocket)
            effective_username = (
                username
                or (session.get_player_username(websocket))
                or (auth["username"] if auth else None)
            )
            session_id = self.session_manager.get_session_id(session)
            room = self.room_manager.get_room_for_client(websocket)
            room_id = room.room_id if room else None

            if effective_username and color and session_id:
                if self._use_local_reconnect and self._reconnect_manager is not None:
                    self._reconnect_manager.start_reconnect(
                        effective_username, color, room_id, session_id
                    )
                else:
                    self._store.reconnect_start(
                        username=effective_username,
                        color=color,
                        room_id=room_id,
                        session_id=session_id,
                        timeout_seconds=RECONNECT_TIMEOUT,
                    )
                logger.info(
                    f"Reconnect reservation: username={effective_username} "
                    f"color={color} session={session_id}"
                )
                msg = make_player_disconnected(effective_username, color, int(RECONNECT_TIMEOUT))
                session.queue_broadcast(msg)
                self.session_manager.remove_client(websocket)
                return

        self.room_manager.remove_client(websocket)
        if session:
            session.remove_client(websocket)
        self.session_manager.remove_client(websocket)

    # ─── Periodic processing ───────────────────────────────────────────────

    async def process_matchmaking(self, send: SendFunc) -> None:
        """Check for matches and timeouts using the shared store."""
        # Handle timeouts (store-based)
        timed_out = self._store.matchmaking_get_timed_out(
            self._local_mm._timeout_seconds
        )
        for entry in timed_out:
            ws = self._find_ws_by_username(entry.username)
            if ws:
                try:
                    await send(ws, make_matchmaking_timeout())
                except Exception:
                    pass

        # Also handle local-mm timeouts (covers tests that bypass the store)
        for entry in self._local_mm.get_timed_out():
            try:
                await send(entry.websocket, make_matchmaking_timeout())
            except Exception:
                pass

        # Try to match using the store first; if it succeeded skip local.
        store_matched = await self._try_match_from_store(send)

        # Fall back to local queue only when the store produced no match.
        # This covers tests that populate only the local mm (without a store).
        if not store_matched:
            await self._try_match_local(send)

    async def _try_match_from_store(self, send: SendFunc) -> bool:
        """
        Attempt to find a compatible pair in the shared store queue.

        Returns True if a match was made (so the caller can skip the local
        queue check for the same poll cycle).
        """
        entries = self._store.matchmaking_get_all()
        threshold = self._local_mm._rating_threshold
        for i, e1 in enumerate(entries):
            for e2 in entries[i + 1:]:
                if abs(e1.rating - e2.rating) <= threshold:
                    # Match found — remove from both store AND local queue
                    self._store.matchmaking_remove(e1.username)
                    self._store.matchmaking_remove(e2.username)
                    ws1 = self._find_ws_by_username(e1.username)
                    ws2 = self._find_ws_by_username(e2.username)
                    # Keep local queue in sync
                    if ws1:
                        self._local_mm.remove_by_websocket(ws1)
                    if ws2:
                        self._local_mm.remove_by_websocket(ws2)
                    if ws1 and ws2:
                        await self._start_matched_game(
                            ws1, e1.username, e1.rating,
                            ws2, e2.username, e2.rating,
                            send,
                        )
                    return True
        return False

    async def _try_match_local(self, send: SendFunc) -> None:
        """
        Fallback: match from the local in-memory queue (test compat).

        Only runs when the store queue produced no match this cycle.
        """
        match = self._local_mm.try_match()
        if match is None:
            return
        p1, p2 = match.player1, match.player2
        # Keep store in sync
        self._store.matchmaking_remove(p1.username)
        self._store.matchmaking_remove(p2.username)
        await self._start_matched_game(
            p1.websocket, p1.username, p1.rating,
            p2.websocket, p2.username, p2.rating,
            send,
        )

    async def _start_matched_game(
        self,
        ws1, username1: str, rating1: int,
        ws2, username2: str, rating2: int,
        send: SendFunc,
    ) -> None:
        logger.info(f"Match found: {username1} ({rating1}) vs {username2} ({rating2})")
        session = self.session_manager.create_session()
        await session.start_tick_loop()

        session.add_client(ws1)
        session.add_client(ws2)
        session.login_client(ws1, username1, rating=rating1)
        session.login_client(ws2, username2, rating=rating2)

        self.session_manager.assign_client_to_session(ws1, session)
        self.session_manager.assign_client_to_session(ws2, session)

        if self.rating_service:
            session_id = self.session_manager.get_session_id(session)
            self._subscribe_rating_updates(session, session_id)

        # Update routing metadata in shared store
        session_id = self.session_manager.get_session_id(session)
        if session_id:
            self._store.player_set_room(username1, session_id)
            self._store.player_set_room(username2, session_id)
            self._store.room_set_server(session_id, self._store._server_id)

        try:
            await send(ws1, make_match_found(
                opponent_username=username2, color="w",
                own_rating=rating1, opponent_rating=rating2,
            ))
        except Exception:
            pass
        try:
            await send(ws2, make_match_found(
                opponent_username=username1, color="b",
                own_rating=rating2, opponent_rating=rating1,
            ))
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
        """Handle expired reconnect records — auto-resign."""
        # Local reconnect manager (injected, used by tests)
        if self._use_local_reconnect and self._reconnect_manager is not None:
            await self._expire_from_local_manager()
            return
        # Store-based (production)
        await self._expire_from_store()

    async def _expire_from_local_manager(self) -> None:
        expired = self._reconnect_manager.get_expired()
        for record in expired:
            await self._handle_expiry(
                username=record.username,
                color=record.color,
                session_id=record.session_id,
            )

    async def _expire_from_store(self) -> None:
        all_entries = self._store.reconnect_get_all()
        now = __import__("time").monotonic()
        for entry in all_entries:
            if now >= entry.deadline:
                self._store.reconnect_cancel(entry.username)
                await self._handle_expiry(
                    username=entry.username,
                    color=entry.color,
                    session_id=entry.session_id,
                )

    async def _handle_expiry(self, username: str, color: str, session_id: str) -> None:
        logger.warning(
            f"Reconnect timeout: username={username} color={color} session={session_id}"
        )
        session = self.session_manager.get_session_by_id(session_id)
        if session is None or session.engine.game_over:
            return

        winner_color = "b" if color == "w" else "w"
        loser_color = color

        msg = make_game_ended(winner=winner_color, loser=loser_color)
        session.engine.game_over = True
        session.queue_broadcast(msg)

        if self.rating_service:
            winner_username = session.get_username_for_color(winner_color)
            if winner_username:
                self.rating_service.process_game_end(
                    game_id=session_id,
                    winner_username=winner_username,
                    loser_username=username,
                )

        await session.drain_outbox()

    # ─── Private handlers ──────────────────────────────────────────────────

    def _handle_login_request(self, payload: dict, sender) -> str | list[str]:
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

        self._authenticated[sender] = {"username": canonical_username, "rating": rating}
        self._ws_username[sender] = canonical_username

        # Check for pending reconnect
        pending = self._get_pending_reconnect(canonical_username)
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

    def _get_pending_reconnect(self, username: str):
        """Return a pending reconnect record (local or store-based)."""
        if self._use_local_reconnect and self._reconnect_manager is not None:
            return self._reconnect_manager.try_reconnect(username)
        return self._store.reconnect_get(username)

    def _cancel_reconnect(self, username: str) -> None:
        """Cancel a pending reconnect (local or store-based)."""
        if self._use_local_reconnect and self._reconnect_manager is not None:
            self._reconnect_manager.cancel(username)
        else:
            self._store.reconnect_cancel(username)

    def _handle_reconnect(self, websocket, pending, username: str, rating: int) -> str | list[str]:
        session = self.session_manager.get_session_by_id(pending.session_id)
        if session is None or session.engine.game_over:
            self._cancel_reconnect(username)
            logger.warning(f"Reconnect failed: username={username} reason=game_no_longer_available")
            return make_error("game no longer available", "reconnect_failed")

        self._cancel_reconnect(username)
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
        auth = self._authenticated.get(sender)
        if auth is None:
            return make_error("must login first", "not_logged_in")

        if self.session_manager.is_client_in_session(sender):
            return make_error("already in a game", "already_in_game")

        username = auth["username"]
        rating = auth["rating"]

        # Try shared store first (production); fall back to local (tests)
        added_to_store = self._store.matchmaking_enqueue(username, rating)
        if not added_to_store:
            # Also check local queue
            if self._local_mm.is_queued(sender):
                return make_error("already in matchmaking queue", "already_queued")
            # Already in shared queue
            return make_error("already in matchmaking queue", "already_queued")

        # Also enqueue in local mm so local tests still work via srv.matchmaking
        self._local_mm.enqueue(sender, username, rating)

        logger.info(f"Matchmaking: {username} entered queue (rating={rating})")
        return make_matchmaking_started()

    def _handle_cancel_matchmaking(self, sender) -> str:
        username = self._ws_username.get(sender) or ""
        removed_store = bool(self._store.matchmaking_remove(username))
        removed_local = self._local_mm.cancel(sender)
        if removed_store or removed_local:
            return make_matchmaking_cancelled()
        return make_error("not in matchmaking queue", "not_queued")

    async def _handle_create_room(self, sender) -> str:
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

        # Record routing metadata
        session_id = self.session_manager.get_session_id(room.session)
        if session_id:
            self._store.room_set_server(session_id, self._store._server_id)

        logger.info(f"Room created: room_id={room.room_id} creator={auth['username']}")
        return make_room_created(room.room_id)

    async def _handle_join_room(self, payload: dict, sender) -> str | list[str]:
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

        # Record player→room routing metadata
        session_id = self.session_manager.get_session_id(room.session)
        if session_id and role == "player":
            self._store.player_set_room(auth["username"], session_id)

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
        room = self.room_manager.get_room_for_client(sender)
        if room is None:
            return make_error("not in a room", "not_in_room")

        username = self._ws_username.get(sender, "")
        if username:
            self._store.player_clear_room(username)

        self.room_manager.remove_client(sender)
        session = self.session_manager.get_session_for_client(sender)
        if session:
            session.remove_client(sender)
        self.session_manager.remove_client(sender)

        return encode_message("room_left", {})

    def _subscribe_rating_updates(self, session: GameSession, session_id: str) -> None:
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

    def _find_ws_by_username(self, username: str):
        """Look up the websocket for an authenticated user on this server."""
        for ws, info in self._authenticated.items():
            if info.get("username") == username:
                return ws
        return None


# ─── Backward-compat shim ─────────────────────────────────────────────────────

class _MatchmakingShim:
    """
    Proxy that exposes queue_size, is_queued etc. from the store.

    Tests access srv.matchmaking.queue_size — this shim lets them
    work without changing any test code.
    """
    def __init__(self, store, local_mm: MatchmakingService):
        self._store = store
        self._local = local_mm

    @property
    def queue_size(self) -> int:
        # Use whichever is non-zero (store-based in production,
        # local-based in tests)
        store_size = self._store.matchmaking_get_queue_size()
        local_size = self._local.queue_size
        return max(store_size, local_size)

    def is_queued(self, websocket) -> bool:
        return self._local.is_queued(websocket)

    @property
    def _timeout_seconds(self) -> float:
        return self._local._timeout_seconds

    @property
    def _rating_threshold(self) -> int:
        return self._local._rating_threshold

    def get_timed_out(self) -> list:
        return self._local.get_timed_out()

    def try_match(self):
        return self._local.try_match()

    def cancel(self, websocket) -> bool:
        return self._local.cancel(websocket)

    def remove_by_websocket(self, websocket):
        return self._local.remove_by_websocket(websocket)

    def enqueue(self, websocket, username: str, rating: int) -> bool:
        return self._local.enqueue(websocket, username, rating)
