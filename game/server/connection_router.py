"""
Application-level routing for WebSocket clients.

Stage 4: Adds cross-server command forwarding via InternalMessageBus.

Local flow (unchanged):
  client → route_message → local GameSession

Remote flow (new):
  client → route_message → internal bus → owner server → GameSession
                                                        ↓
  client ←  events channel ← game response ←───────────┘

room_id is now the canonical external identifier stored in Redis.
session_id remains the internal GameSession lookup key.
Both are stored in the shared store so tests using either key still pass.
"""

import logging
import uuid
from typing import Callable, Awaitable

from game.model.constants import DEFAULT_RATING
from game.server.auth.user_service import UserService
from game.server.game_session import GameSession
from game.server.game_session_manager import GameSessionManager
from game.server.internal_bus import (
    NullInternalMessageBus,
    commands_channel,
    events_channel,
    make_game_command,
    make_game_response,
)
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

# Game message types that may need cross-server forwarding
_GAME_MSG_TYPES = {"move_request", "jump_request", "ping"}


class ClientSessionRouter:
    """
    Application-layer coordinator for multiplayer game connections.

    Stage 4 additions:
    - bus: InternalMessageBus for cross-server command forwarding.
    - route_message checks room ownership; forwards to peer if not local.
    - Handles inbound GameCommand messages (owner side).
    - Handles inbound GameResponse messages (gateway side).
    - room_id is now also stored as the routing key alongside session_id.
    - player→server mapping updated on login/disconnect.
    """

    def __init__(
        self,
        user_service: UserService | None = None,
        rating_service: RatingService | None = None,
        matchmaking: MatchmakingService | None = None,
        session_manager: GameSessionManager | None = None,
        reconnect_manager=None,
        room_manager: RoomManager | None = None,
        *,
        legacy_session: GameSession | None = None,
        store=None,
        allocator=None,
        bus=None,
    ):
        self.user_service = user_service
        self.rating_service = rating_service
        self.session_manager = session_manager or GameSessionManager()
        self.room_manager = room_manager or RoomManager(self.session_manager)

        self._store = store or NullRedisStore()

        if allocator is None:
            from game.server.game_allocator import NullGameAllocator
            allocator = NullGameAllocator(own_server_id=self._store._server_id)
        self._allocator = allocator

        # Stage 4: internal message bus (defaults to NullInternalMessageBus)
        self._bus = bus or NullInternalMessageBus()

        self._local_mm = matchmaking or MatchmakingService()

        if reconnect_manager is not None:
            self._reconnect_manager = reconnect_manager
            self._use_local_reconnect = True
        else:
            self._reconnect_manager = None
            self._use_local_reconnect = False

        self._authenticated: dict = {}   # websocket → {"username", "rating"}
        self._ws_username: dict = {}      # websocket → username

        self.legacy_session = legacy_session
        if legacy_session is not None:
            self.session_manager.register_session(legacy_session)

    # ─── Backward-compat shims ─────────────────────────────────────────────

    @property
    def matchmaking(self):
        return _MatchmakingShim(self._store, self._local_mm)

    @property
    def reconnect_manager(self):
        return self._reconnect_manager

    # ─── Stage 4: bus registration ─────────────────────────────────────────

    def register_bus_handlers(self) -> None:
        """
        Subscribe this router to its own command and event channels.

        Called once at server startup (after the bus is ready).
        - commands channel: owner side — process forwarded game messages.
        - events channel:   gateway side — deliver results back to clients.
        """
        own_id = self._allocator.own_server_id
        self._bus.subscribe(commands_channel(own_id), self._handle_inbound_command)
        self._bus.subscribe(events_channel(own_id), self._handle_inbound_response)
        logger.info(
            f"Router subscribed to bus channels for server {own_id!r}"
        )

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

        # ── Gameplay messages: check local session first, then cross-server ──

        session = self.session_manager.get_session_for_client(sender)
        if session:
            return await session.handle_message(raw, sender=sender)

        if self.legacy_session is not None:
            return await self.legacy_session.handle_message(raw, sender=sender)

        # Stage 4: client not in a local session — check for remote ownership
        if msg is not None and msg.get("type") in _GAME_MSG_TYPES:
            forwarded = await self._try_forward_to_owner(msg, sender)
            if forwarded is not None:
                return forwarded

        return make_error("not in a game session", "no_session")

    # ─── Stage 4: cross-server forwarding (gateway side) ──────────────────

    async def _try_forward_to_owner(self, msg: dict, sender) -> str | None:
        """
        If a game message belongs to a remotely-owned room, forward it.

        Returns an immediate error string if routing fails, or None to
        signal that the message was forwarded (no direct response yet).
        """
        auth = self._authenticated.get(sender)
        if auth is None:
            return None   # not authenticated → fall through to "no_session"

        username = auth["username"]
        # Find which room this player is in
        room_id = self._store.player_get_room(username)
        if room_id is None:
            return None

        owner_id = self._store.room_get_server(room_id)
        if owner_id is None:
            return None

        own_id = self._allocator.own_server_id
        if owner_id == own_id:
            # We are the owner — but the session is missing locally.
            # This should not happen in normal flow; fall through.
            return None

        # Remote owner — publish command to its commands channel
        cmd_msg = make_game_command(
            source_server=own_id,
            target_server=owner_id,
            room_id=room_id,
            username=username,
            cmd=msg.get("type", ""),
            payload=msg.get("payload", {}),
        )
        try:
            await self._bus.publish_async(commands_channel(owner_id), cmd_msg)
            logger.debug(
                f"Forwarded {cmd_msg['cmd']!r} for room {room_id!r} "
                f"to owner {owner_id!r} (request_id={cmd_msg['request_id']!r})"
            )
        except Exception as exc:
            logger.error(f"Bus publish failed for room {room_id!r}: {exc}")
            return make_error("could not forward command to game server", "routing_error")

        # Return None: response arrives asynchronously via the events channel
        return None

    # ─── Stage 4: inbound command (owner side) ────────────────────────────

    async def _handle_inbound_command(self, msg: dict) -> None:
        """
        Process a GameCommand that arrived from a gateway server.

        We are the authoritative owner.  Find the session, process the
        message as if the player were local, collect response + broadcasts,
        and publish a GameResponse back to the source server's events channel.
        """
        room_id = msg.get("room_id", "")
        username = msg.get("username", "")
        cmd = msg.get("cmd", "")
        payload = msg.get("payload", {})
        request_id = msg.get("request_id", "")
        source_server = msg.get("source_server", "")

        logger.debug(
            f"Inbound command: cmd={cmd!r} room={room_id!r} "
            f"user={username!r} from={source_server!r}"
        )

        # Resolve session via room_id → session_id mapping
        session = self._resolve_session_by_room(room_id)
        if session is None:
            logger.warning(f"Inbound command: no session for room {room_id!r}")
            resp = make_game_response(
                source_server=self._allocator.own_server_id,
                target_server=source_server,
                room_id=room_id,
                username=username,
                request_id=request_id,
                response=make_error("game session not found", "no_session"),
                broadcasts=[],
            )
            await self._bus.publish_async(events_channel(source_server), resp)
            return

        # Build a fake wire message so session.handle_message() can parse it
        from game.server.protocol import encode_message
        raw = encode_message(cmd, payload)

        # Use a sentinel object as the "sender" since we have no websocket here
        sentinel = _RemoteSender(username)
        # Patch the session's player_colors so it recognises the sentinel
        color = session.get_username_for_color("w")   # find color by username
        actual_color = None
        for ws, uname in session._player_usernames.items():
            if uname == username:
                actual_color = session._player_colors.get(ws)
                break

        if actual_color is not None:
            # Temporarily register sentinel so session can do ownership check
            session._player_colors[sentinel] = actual_color
            session._player_usernames[sentinel] = username
            session._clients.add(sentinel)

        try:
            direct_response = await session.handle_message(raw, sender=sentinel)
            broadcasts = session.get_pending_broadcasts()
        finally:
            # Always clean up the sentinel
            session._clients.discard(sentinel)
            session._player_colors.pop(sentinel, None)
            session._player_usernames.pop(sentinel, None)

        resp = make_game_response(
            source_server=self._allocator.own_server_id,
            target_server=source_server,
            room_id=room_id,
            username=username,
            request_id=request_id,
            response=direct_response,
            broadcasts=broadcasts,
        )
        await self._bus.publish_async(events_channel(source_server), resp)
        logger.debug(
            f"Responded to {cmd!r} for room {room_id!r}: "
            f"direct={direct_response is not None} broadcasts={len(broadcasts)}"
        )

    # ─── Stage 4: inbound response (gateway side) ─────────────────────────

    async def _handle_inbound_response(self, msg: dict) -> None:
        """
        Process a GameResponse that arrived from the owner server.

        We are the gateway: find the player's websocket and deliver:
        - the direct response (if any) to the player who sent the command,
        - the broadcasts to ALL connected clients in that room.
        """
        username = msg.get("username", "")
        room_id = msg.get("room_id", "")
        direct = msg.get("response")
        broadcasts = msg.get("broadcasts", [])

        logger.debug(
            f"Inbound response: room={room_id!r} user={username!r} "
            f"direct={direct is not None} broadcasts={len(broadcasts)}"
        )

        # Deliver direct response to the originating client
        ws = self._find_ws_by_username(username)
        if ws is not None and direct is not None:
            try:
                await ws.send(direct)
            except Exception as exc:
                logger.warning(f"Could not send direct response to {username!r}: {exc}")

        # Deliver broadcasts to all clients in that room
        if broadcasts:
            await self._broadcast_to_room(room_id, broadcasts)

    async def _broadcast_to_room(self, room_id: str, messages: list[str]) -> None:
        """Send broadcast messages to all locally-connected members of a room."""
        room = self.room_manager.get_room(room_id)
        if room is None:
            # Try to find connected clients by username via player_get_room reverse
            # Fall back to sending to any client whose room_id matches
            for ws, info in list(self._authenticated.items()):
                uname = info.get("username", "")
                if self._store.player_get_room(uname) == room_id:
                    for m in messages:
                        try:
                            await ws.send(m)
                        except Exception:
                            pass
            return

        recipients = list(room.players) + list(room.viewers)
        for ws in recipients:
            for m in messages:
                try:
                    await ws.send(m)
                except Exception:
                    pass

    def _resolve_session_by_room(self, room_id: str) -> "GameSession | None":
        """
        Find the authoritative GameSession for a room on this server.

        Tries:
        1. Direct local room lookup by room_id (handles create_room path).
        2. session_id via room→session mapping in the store (handles matchmaking path).
        """
        room = self.room_manager.get_room(room_id)
        if room is not None:
            return room.session

        session_id = self._store.room_get_session(room_id)
        if session_id:
            return self.session_manager.get_session_by_id(session_id)

        return None

    def on_disconnect(self, websocket) -> None:
        """Handle client disconnect."""
        username = self._ws_username.pop(websocket, None)
        if username:
            self._store.matchmaking_remove(username)
            self._store.player_clear_server(username)   # Stage 4
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
        timed_out = self._store.matchmaking_get_timed_out(self._local_mm._timeout_seconds)
        for entry in timed_out:
            ws = self._find_ws_by_username(entry.username)
            if ws:
                try:
                    await send(ws, make_matchmaking_timeout())
                except Exception:
                    pass

        for entry in self._local_mm.get_timed_out():
            try:
                await send(entry.websocket, make_matchmaking_timeout())
            except Exception:
                pass

        store_matched = await self._try_match_from_store(send)
        if not store_matched:
            await self._try_match_local(send)

    async def _try_match_from_store(self, send: SendFunc) -> bool:
        entries = self._store.matchmaking_get_all()
        threshold = self._local_mm._rating_threshold
        for i, e1 in enumerate(entries):
            for e2 in entries[i + 1:]:
                if abs(e1.rating - e2.rating) <= threshold:
                    self._store.matchmaking_remove(e1.username)
                    self._store.matchmaking_remove(e2.username)
                    ws1 = self._find_ws_by_username(e1.username)
                    ws2 = self._find_ws_by_username(e2.username)
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
        match = self._local_mm.try_match()
        if match is None:
            return
        p1, p2 = match.player1, match.player2
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

        owner_id = self._allocator.allocate_server()
        is_local = self._allocator.is_local(owner_id)
        own_id = self._allocator.own_server_id

        if not is_local:
            import uuid as _uuid
            session_id = f"remote-{_uuid.uuid4().hex[:8]}"
            self._store.player_set_room(username1, session_id)
            self._store.player_set_room(username2, session_id)
            self._store.room_set_server(session_id, owner_id)
            # Stage 4: record which server each player is connected to
            self._store.player_set_server(username1, own_id)
            self._store.player_set_server(username2, own_id)
            logger.info(
                f"Match allocated to peer {owner_id!r}; routing metadata stored."
            )
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
            return

        # Local ownership
        session = self.session_manager.create_session()
        await session.start_tick_loop()

        session.add_client(ws1)
        session.add_client(ws2)
        session.login_client(ws1, username1, rating=rating1)
        session.login_client(ws2, username2, rating=rating2)

        self.session_manager.assign_client_to_session(ws1, session)
        self.session_manager.assign_client_to_session(ws2, session)

        session_id = self.session_manager.get_session_id(session)

        if self.rating_service and session_id:
            self._subscribe_rating_updates(session, session_id)

        if session_id:
            # Stage 4: store both session_id (legacy) and session_id as room id
            # For matchmaking games the session_id IS the external room key.
            self._store.player_set_room(username1, session_id)
            self._store.player_set_room(username2, session_id)
            self._store.room_set_server(session_id, owner_id)
            self._store.room_set_session(session_id, session_id)  # identity mapping
            self._store.player_set_server(username1, own_id)      # Stage 4
            self._store.player_set_server(username2, own_id)      # Stage 4
            self._store.server_increment_rooms(owner_id)
            self._subscribe_room_count_decrement(session, owner_id)

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
        if self._use_local_reconnect and self._reconnect_manager is not None:
            await self._expire_from_local_manager()
            return
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

    # ─── Private login/room handlers ──────────────────────────────────────

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
            logger.warning(
                f"Login failed: username={username} action={action} error={result.error}"
            )
            return make_error(
                result.error or "authentication failed",
                result.error or "invalid_credentials",
            )

        canonical_username = result.user.username if result.user else username
        rating = result.user.rating if result.user else DEFAULT_RATING
        logger.info(f"Login success: username={canonical_username} action={action}")

        self._authenticated[sender] = {"username": canonical_username, "rating": rating}
        self._ws_username[sender] = canonical_username

        # Stage 4: record which server this player is connected to
        self._store.player_set_server(canonical_username, self._allocator.own_server_id)

        pending = self._get_pending_reconnect(canonical_username)
        if pending:
            return self._handle_reconnect(sender, pending, canonical_username, rating)

        if self.legacy_session is not None:
            messages = self.legacy_session.login_client(sender, canonical_username, rating=rating)
            self.session_manager.assign_client_to_session(sender, self.legacy_session)
            if len(messages) == 1:
                return messages[0]
            return messages

        return make_login_success(username=canonical_username, color="", rating=rating)

    def _get_pending_reconnect(self, username: str):
        if self._use_local_reconnect and self._reconnect_manager is not None:
            return self._reconnect_manager.try_reconnect(username)
        return self._store.reconnect_get(username)

    def _cancel_reconnect(self, username: str) -> None:
        if self._use_local_reconnect and self._reconnect_manager is not None:
            self._reconnect_manager.cancel(username)
        else:
            self._store.reconnect_cancel(username)

    def _handle_reconnect(self, websocket, pending, username: str, rating: int) -> str | list[str]:
        session = self.session_manager.get_session_by_id(pending.session_id)
        if session is None or session.engine.game_over:
            self._cancel_reconnect(username)
            logger.warning(
                f"Reconnect failed: username={username} reason=game_no_longer_available"
            )
            return make_error("game no longer available", "reconnect_failed")

        self._cancel_reconnect(username)
        logger.info(
            f"Reconnect success: username={username} color={pending.color} "
            f"session={pending.session_id}"
        )

        session.restore_player(websocket, pending.color, username)
        self.session_manager.assign_client_to_session(websocket, session)

        if pending.room_id:
            room = self.room_manager.get_room(pending.room_id)
            if room and websocket not in room.players:
                room.players.append(websocket)

        msg = make_player_reconnected(username, pending.color)
        session.queue_broadcast(msg)

        messages = [
            make_login_success(
                username=username, color=pending.color, rating=rating, reconnected=True
            ),
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

        added_to_store = self._store.matchmaking_enqueue(username, rating)
        if not added_to_store:
            if self._local_mm.is_queued(sender):
                return make_error("already in matchmaking queue", "already_queued")
            return make_error("already in matchmaking queue", "already_queued")

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

        owner_id = self._allocator.allocate_server()
        is_local = self._allocator.is_local(owner_id)
        own_id = self._allocator.own_server_id

        if not is_local:
            room_id = uuid.uuid4().hex[:8]
            self._store.room_set_server(room_id, owner_id)
            self._store.player_set_server(auth["username"], own_id)  # Stage 4
            logger.info(
                f"Room {room_id!r} allocated to peer {owner_id!r}; no local session."
            )
            return make_room_created(room_id)

        # Local ownership
        room = self.room_manager.create_room()
        error, role = self.room_manager.join_room(
            room.room_id, sender, auth["username"], auth["rating"]
        )
        if error:
            return make_error(error, error)

        await room.session.start_tick_loop()

        session_id = self.session_manager.get_session_id(room.session)
        if session_id:
            # Store BOTH room_id (canonical) and session_id (legacy compat)
            self._store.room_set_server(room.room_id, owner_id)   # canonical
            self._store.room_set_server(session_id, owner_id)     # backward compat
            self._store.room_set_session(room.room_id, session_id)
            self._store.player_set_room(auth["username"], room.room_id)
            self._store.player_set_server(auth["username"], own_id)  # Stage 4
            self._store.server_increment_rooms(owner_id)
            self._subscribe_room_count_decrement(room.session, owner_id)

        logger.info(
            f"Room created: room_id={room.room_id} "
            f"creator={auth['username']} owner={owner_id!r}"
        )
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

        session_id = self.session_manager.get_session_id(room.session)
        if session_id and role == "player":
            self._store.player_set_room(auth["username"], room_id)

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

    def _subscribe_room_count_decrement(self, session: GameSession, server_id: str) -> None:
        from game.events.engine_events import GameEnded

        _decremented = [False]

        def on_game_ended(event):
            if _decremented[0]:
                return
            _decremented[0] = True
            try:
                self._store.server_decrement_rooms(server_id)
                logger.debug(f"Room count decremented for server {server_id!r}")
            except Exception as exc:
                logger.warning(f"Could not decrement room count: {exc}")

        session.engine.event_bus.subscribe(GameEnded, on_game_ended)

    def _find_ws_by_username(self, username: str):
        for ws, info in self._authenticated.items():
            if info.get("username") == username:
                return ws
        return None


# ─── Sentinel object for remote command processing ────────────────────────────

class _RemoteSender:
    """
    Placeholder used as the 'sender' when processing a forwarded command.

    The real websocket lives on the gateway server.  We only need an
    object that can be used as a dict key and compared by identity.
    Equality is intentionally object-identity so each sentinel is unique.
    """

    def __init__(self, username: str):
        self.username = username

    def __repr__(self) -> str:
        return f"<RemoteSender username={self.username!r}>"


# ─── Backward-compat shim ─────────────────────────────────────────────────────

class _MatchmakingShim:
    def __init__(self, store, local_mm: MatchmakingService):
        self._store = store
        self._local = local_mm

    @property
    def queue_size(self) -> int:
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
