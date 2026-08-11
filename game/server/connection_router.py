"""
Application-level routing for WebSocket clients.

Stage 5: Complete end-to-end cross-server gameplay.

Local flow (single-server, unchanged):
  client → route_message → local GameSession → broadcast

Remote create_room flow:
  client → route_message → publish create_room_cmd to owner
  owner creates Room+Session → publishes room_event back
  gateway _handle_inbound_room_event → ws.send(room_created)

Remote join_room flow:
  client → route_message → publish join_room_cmd to owner
  owner adds player/viewer → publishes room_event back
  gateway → ws.send(room_joined + game_state)

Cross-server matchmaking:
  matchmaker → publish create_session_cmd to owner
  owner creates session → publishes broadcast_event to both connection servers
  each connection server delivers match_found + game_state to its local clients

Cross-server gameplay (move/jump):
  client → route_message → publish game_command to owner
  owner processes GameSession → fan-out broadcast_event to ALL connection servers

Cross-server reconnect:
  client logs in → pending reconnect found → session not local
  → publish reconnect_cmd to owner
  owner restore_player → publishes room_event + broadcast_event back

Broadcast fan-out rule (Stage 5):
  after any game action the owner collects all unique connection servers
  from store.player_get_server() for every player in the session,
  then publishes one broadcast_event per connection server.

Invariants:
  - WebSocket objects never leave the server they were created on.
  - Redis stores routing/coordination metadata only.
  - GameEngine is the single source of truth; never duplicated.
  - All new remote paths are guarded by allocator.is_local() checks.
  - NullGameAllocator.is_local() always returns True → single-server
    and all unit tests are completely unaffected.
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
    make_create_room_cmd,
    make_join_room_cmd,
    make_create_session_cmd,
    make_reconnect_cmd,
    make_room_event,
    make_broadcast_event,
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

# Gameplay message types that may need cross-server forwarding
_GAME_MSG_TYPES = {"move_request", "jump_request", "ping"}


class ClientSessionRouter:
    """Application-layer coordinator for multiplayer game connections."""

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

    # ── Backward-compat shims ──────────────────────────────────────────────

    @property
    def matchmaking(self):
        return _MatchmakingShim(self._store, self._local_mm)

    @property
    def reconnect_manager(self):
        return self._reconnect_manager

    # ── Bus registration ───────────────────────────────────────────────────

    def register_bus_handlers(self) -> None:
        """Subscribe to own command and event channels on startup."""
        own_id = self._allocator.own_server_id
        self._bus.subscribe(commands_channel(own_id), self._handle_inbound_command)
        self._bus.subscribe(events_channel(own_id), self._handle_inbound_event)
        logger.info(f"Router subscribed to bus channels for server {own_id!r}")

    # ── Main entry point ───────────────────────────────────────────────────

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

        # Gameplay: local session first, then cross-server
        session = self.session_manager.get_session_for_client(sender)
        if session:
            return await session.handle_message(raw, sender=sender)

        if self.legacy_session is not None:
            return await self.legacy_session.handle_message(raw, sender=sender)

        if msg is not None and msg.get("type") in _GAME_MSG_TYPES:
            forwarded = await self._try_forward_to_owner(msg, sender)
            if forwarded is not None:
                return forwarded

        return make_error("not in a game session", "no_session")

    # ── Gateway side: forward gameplay to owner ────────────────────────────

    async def _try_forward_to_owner(self, msg: dict, sender) -> str | None:
        auth = self._authenticated.get(sender)
        if auth is None:
            return None
        username = auth["username"]
        room_id = self._store.player_get_room(username)
        if room_id is None:
            return None
        owner_id = self._store.room_get_server(room_id)
        if owner_id is None:
            return None
        own_id = self._allocator.own_server_id
        if owner_id == own_id:
            return None   # We own it but session is missing — fall through

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
                f"Forwarded {cmd_msg['cmd']!r} room={room_id!r} "
                f"owner={owner_id!r} req={cmd_msg['request_id']!r}"
            )
        except Exception as exc:
            logger.error(f"Bus publish failed for room {room_id!r}: {exc}")
            return make_error("could not forward command to game server", "routing_error")
        return None   # response arrives async

    # ── Owner side: inbound commands dispatcher ────────────────────────────

    async def _handle_inbound_command(self, msg: dict) -> None:
        """Dispatch inbound bus commands by type."""
        msg_type = msg.get("type", "")
        if msg_type == "game_command":
            await self._owner_handle_game_command(msg)
        elif msg_type == "create_room_cmd":
            await self._owner_handle_create_room(msg)
        elif msg_type == "join_room_cmd":
            await self._owner_handle_join_room(msg)
        elif msg_type == "create_session_cmd":
            await self._owner_handle_create_session(msg)
        elif msg_type == "reconnect_cmd":
            await self._owner_handle_reconnect(msg)
        else:
            logger.warning(f"Unknown inbound command type: {msg_type!r}")

    async def _owner_handle_game_command(self, msg: dict) -> None:
        """Process a forwarded move/jump request on the authoritative session."""
        room_id = msg.get("room_id", "")
        username = msg.get("username", "")
        cmd = msg.get("cmd", "")
        payload = msg.get("payload", {})
        request_id = msg.get("request_id", "")
        source_server = msg.get("source_server", "")

        session = self._resolve_session_by_room(room_id)
        if session is None:
            logger.warning(f"game_command: no session for room {room_id!r}")
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

        from game.server.protocol import encode_message as _enc
        raw = _enc(cmd, payload)
        sentinel = _RemoteSender(username)
        actual_color = None
        for ws, uname in session._player_usernames.items():
            if uname == username:
                actual_color = session._player_colors.get(ws)
                break

        if actual_color is not None:
            session._player_colors[sentinel] = actual_color
            session._player_usernames[sentinel] = username
            session._clients.add(sentinel)

        try:
            direct_response = await session.handle_message(raw, sender=sentinel)
            broadcasts = session.get_pending_broadcasts()
        finally:
            session._clients.discard(sentinel)
            session._player_colors.pop(sentinel, None)
            session._player_usernames.pop(sentinel, None)

        # Stage 5: fan-out broadcasts to ALL connection servers
        await self._fanout_broadcasts(session, room_id, broadcasts, primary_server=source_server)

        # Direct response goes only to the requesting server
        if direct_response is not None:
            resp = make_game_response(
                source_server=self._allocator.own_server_id,
                target_server=source_server,
                room_id=room_id,
                username=username,
                request_id=request_id,
                response=direct_response,
                broadcasts=[],
            )
            await self._bus.publish_async(events_channel(source_server), resp)

    async def _owner_handle_create_room(self, msg: dict) -> None:
        """Owner: create a Room+Session for a remote client, respond with metadata."""
        source_server = msg.get("source_server", "")
        room_id = msg.get("room_id", "")
        username = msg.get("username", "")
        rating = msg.get("rating", DEFAULT_RATING)
        request_id = msg.get("request_id", "")
        own_id = self._allocator.own_server_id

        # Create the room locally with the pre-assigned room_id
        from game.server.room_manager import Room
        from game.server.game_session import GameSession as _GS
        # Use session_manager to create session, then build room manually with given room_id
        session = self.session_manager.create_session()
        await session.start_tick_loop()
        room = Room(room_id=room_id, session=session)
        self.room_manager._rooms[room_id] = room

        # Add the creator as the first player using a persistent RemoteSender.
        # Their websocket lives on source_server, not here, so we keep a
        # RemoteSender placeholder so that room.is_full and session._player_colors
        # correctly reflect the occupied slot when the second player joins.
        sentinel = _RemoteSender(username)
        session._clients.add(sentinel)
        session._player_colors[sentinel] = "w"
        session._player_usernames[sentinel] = username
        room.players.append(sentinel)   # counts toward room.is_full

        session_id = self.session_manager.get_session_id(session)

        # Store routing metadata
        self._store.room_set_server(room_id, own_id)
        self._store.room_set_server(session_id, own_id)   # backward compat
        self._store.room_set_session(room_id, session_id)
        self._store.player_set_room(username, room_id)
        self._store.player_set_server(username, source_server)
        self._store.player_set_color(username, room_id, "w")
        self._store.server_increment_rooms(own_id)
        self._subscribe_room_count_decrement(session, own_id)
        if self.rating_service and session_id:
            pass  # rating subscription deferred until game starts

        game_state = make_game_state(
            board=session.engine.legacy_board,
            clock=session.engine.clock,
            white_score=session.engine.white_score,
            black_score=session.engine.black_score,
            game_over=session.engine.game_over,
        )

        evt = make_room_event(
            event_type="room_created",
            source_server=own_id,
            target_server=source_server,
            room_id=room_id,
            username=username,
            request_id=request_id,
            payload={
                "room_id": room_id,
                "color": "w",
                "game_state": game_state,
            },
        )
        await self._bus.publish_async(events_channel(source_server), evt)
        logger.info(
            f"Owner created remote room {room_id!r} for {username!r} "
            f"(connection server: {source_server!r})"
        )

    async def _owner_handle_join_room(self, msg: dict) -> None:
        """Owner: add a remote player/viewer to an existing room, respond with state."""
        source_server = msg.get("source_server", "")
        room_id = msg.get("room_id", "")
        username = msg.get("username", "")
        rating = msg.get("rating", DEFAULT_RATING)
        request_id = msg.get("request_id", "")
        own_id = self._allocator.own_server_id

        room = self.room_manager.get_room(room_id)
        if room is None:
            # Try session lookup
            session = self._resolve_session_by_room(room_id)
            if session is None:
                evt = make_room_event(
                    event_type="error",
                    source_server=own_id,
                    target_server=source_server,
                    room_id=room_id,
                    username=username,
                    request_id=request_id,
                    payload={"error": "room not found", "code": "room_not_found"},
                )
                await self._bus.publish_async(events_channel(source_server), evt)
                return

        session = room.session
        # Assign role/color
        if room.is_full:
            role = "viewer"
            color = None
        else:
            role = "player"
            # Assign next available color
            taken = set(session._player_colors.values())
            color = "b" if "w" in taken else "w"

        # Record the remote player in metadata (no local websocket)
        self._store.player_set_room(username, room_id)
        self._store.player_set_server(username, source_server)
        if color:
            self._store.player_set_color(username, room_id, color)

        if role == "player":
            # Keep a persistent RemoteSender so room.is_full and
            # session._player_colors correctly reflect the second player slot.
            new_sentinel = _RemoteSender(username)
            room.players.append(new_sentinel)
            session._clients.add(new_sentinel)
            session._player_colors[new_sentinel] = color
            session._player_usernames[new_sentinel] = username
        else:
            new_sentinel = _RemoteSender(username)
            room.viewers.append(new_sentinel)
            session._viewers.add(new_sentinel)

        game_state = make_game_state(
            board=session.engine.legacy_board,
            clock=session.engine.clock,
            white_score=session.engine.white_score,
            black_score=session.engine.black_score,
            game_over=session.engine.game_over,
        )

        evt = make_room_event(
            event_type="room_joined",
            source_server=own_id,
            target_server=source_server,
            room_id=room_id,
            username=username,
            request_id=request_id,
            payload={
                "room_id": room_id,
                "role": role,
                "color": color,
                "game_state": game_state,
            },
        )
        await self._bus.publish_async(events_channel(source_server), evt)

        # If room is now full, broadcast game_state to all connection servers
        if role == "player":
            broadcasts = [game_state]
            await self._fanout_broadcasts(session, room_id, broadcasts)
        logger.info(
            f"Owner joined remote {username!r} to room {room_id!r} "
            f"as {role!r} (server: {source_server!r})"
        )

    async def _owner_handle_create_session(self, msg: dict) -> None:
        """Owner: create an authoritative matchmaking session, notify all connection servers."""
        source_server = msg.get("source_server", "")
        room_id = msg.get("room_id", "")
        p1_user = msg.get("player1_username", "")
        p1_rating = msg.get("player1_rating", DEFAULT_RATING)
        p1_server = msg.get("player1_server", source_server)
        p2_user = msg.get("player2_username", "")
        p2_rating = msg.get("player2_rating", DEFAULT_RATING)
        p2_server = msg.get("player2_server", source_server)
        request_id = msg.get("request_id", "")
        own_id = self._allocator.own_server_id

        session = self.session_manager.create_session()
        await session.start_tick_loop()
        session_id = self.session_manager.get_session_id(session)

        # Store routing metadata
        self._store.player_set_room(p1_user, room_id)
        self._store.player_set_room(p2_user, room_id)
        self._store.player_set_server(p1_user, p1_server)
        self._store.player_set_server(p2_user, p2_server)
        self._store.player_set_color(p1_user, room_id, "w")
        self._store.player_set_color(p2_user, room_id, "b")
        self._store.room_set_server(room_id, own_id)
        self._store.room_set_server(session_id, own_id)
        self._store.room_set_session(room_id, session_id)
        self._store.server_increment_rooms(own_id)
        self._subscribe_room_count_decrement(session, own_id)

        if self.rating_service and session_id:
            self._subscribe_rating_updates(session, session_id)

        game_state = make_game_state(
            board=session.engine.legacy_board,
            clock=session.engine.clock,
            white_score=session.engine.white_score,
            black_score=session.engine.black_score,
            game_over=session.engine.game_over,
        )

        # Notify each player's connection server
        for (uname, color, conn_server, opp_user, opp_rating, own_rating) in [
            (p1_user, "w", p1_server, p2_user, p2_rating, p1_rating),
            (p2_user, "b", p2_server, p1_user, p1_rating, p2_rating),
        ]:
            match_found = make_match_found(
                opponent_username=opp_user,
                color=color,
                own_rating=own_rating,
                opponent_rating=opp_rating,
            )
            evt = make_room_event(
                event_type="session_created",
                source_server=own_id,
                target_server=conn_server,
                room_id=room_id,
                username=uname,
                request_id=request_id,
                payload={
                    "match_found": match_found,
                    "game_state": game_state,
                    "color": color,
                },
            )
            await self._bus.publish_async(events_channel(conn_server), evt)

        logger.info(
            f"Owner created matchmaking session room={room_id!r} "
            f"p1={p1_user!r}@{p1_server!r} p2={p2_user!r}@{p2_server!r}"
        )

    async def _owner_handle_reconnect(self, msg: dict) -> None:
        """Owner: restore a disconnected player and send game state back."""
        source_server = msg.get("source_server", "")
        room_id = msg.get("room_id", "")
        session_id = msg.get("session_id", "")
        username = msg.get("username", "")
        color = msg.get("color", "")
        rating = msg.get("rating", DEFAULT_RATING)
        request_id = msg.get("request_id", "")
        own_id = self._allocator.own_server_id

        session = self._resolve_session_by_room(room_id) or \
                  self.session_manager.get_session_by_id(session_id)

        if session is None or session.engine.game_over:
            evt = make_room_event(
                event_type="error",
                source_server=own_id,
                target_server=source_server,
                room_id=room_id,
                username=username,
                request_id=request_id,
                payload={"error": "game no longer available", "code": "reconnect_failed"},
            )
            await self._bus.publish_async(events_channel(source_server), evt)
            return

        # Update connection-server metadata
        self._store.player_set_server(username, source_server)

        game_state = make_game_state(
            board=session.engine.legacy_board,
            clock=session.engine.clock,
            white_score=session.engine.white_score,
            black_score=session.engine.black_score,
            game_over=session.engine.game_over,
        )

        # Notify the reconnecting player's server
        login_msg = make_login_success(
            username=username, color=color, rating=rating, reconnected=True
        )
        evt = make_room_event(
            event_type="reconnected",
            source_server=own_id,
            target_server=source_server,
            room_id=room_id,
            username=username,
            request_id=request_id,
            payload={
                "login_success": login_msg,
                "game_state": game_state,
            },
        )
        await self._bus.publish_async(events_channel(source_server), evt)

        # Broadcast player_reconnected to all connection servers
        reconnected_msg = make_player_reconnected(username, color)
        await self._fanout_broadcasts(session, room_id, [reconnected_msg])
        logger.info(
            f"Owner reconnected {username!r} to room {room_id!r} "
            f"via {source_server!r}"
        )

    # ── Broadcast fan-out (Stage 5) ────────────────────────────────────────

    async def _fanout_broadcasts(
        self,
        session: GameSession,
        room_id: str,
        broadcasts: list[str],
        primary_server: str | None = None,
    ) -> None:
        """
        Send authoritative broadcasts to every connection server that has
        players or viewers in this room.

        Local clients are sent directly; remote servers receive a
        broadcast_event on their events channel.
        """
        if not broadcasts:
            return

        own_id = self._allocator.own_server_id

        # Collect all usernames in the session
        usernames: list[str] = list(session._player_usernames.values())
        # Also look up any remote-only players registered in the store
        # (players whose WebSocket lives on another server)
        # We use the room_id to find all players via player_get_server
        # For remote players, they won't be in session._player_usernames
        # but their connection server is stored in the store.

        # Build: connection_server → set of usernames
        server_users: dict[str, set] = {}
        for uname in usernames:
            conn_srv = self._store.player_get_server(uname) or own_id
            server_users.setdefault(conn_srv, set()).add(uname)

        # primary_server may have users not yet reflected in the store
        # (e.g. the forwarding server's own player whose server was set locally
        # but not yet propagated).  Only add if it's a NEW server with no users
        # tracked yet AND there is a username we can attribute to it.
        # An empty-set entry still triggers a broadcast_event publication, so we
        # skip the setdefault and only send to servers that actually have users.
        # (The store is always up-to-date for normal connected players.)

        for conn_srv, users in server_users.items():
            if not users:
                continue
            if conn_srv == own_id:
                # Deliver directly to local websockets
                for uname in users:
                    ws = self._find_ws_by_username(uname)
                    if ws is not None:
                        for msg in broadcasts:
                            try:
                                await ws.send(msg)
                            except Exception:
                                pass
                # Also deliver to local room members without usernames tracked above
                room = self.room_manager.get_room(room_id)
                if room:
                    local_ws_users = {
                        ws for ws in (list(room.players) + list(room.viewers))
                        if not isinstance(ws, _RemoteSender)
                    }
                    for ws in local_ws_users:
                        for m in broadcasts:
                            try:
                                await ws.send(m)
                            except Exception:
                                pass
            else:
                # Publish broadcast_event to the remote server
                bcast = make_broadcast_event(
                    source_server=own_id,
                    target_server=conn_srv,
                    room_id=room_id,
                    broadcasts=broadcasts,
                )
                try:
                    await self._bus.publish_async(events_channel(conn_srv), bcast)
                except Exception as exc:
                    logger.warning(
                        f"fanout to {conn_srv!r} failed: {exc}"
                    )

    # ── Gateway side: inbound events from owner ────────────────────────────

    async def _handle_inbound_event(self, msg: dict) -> None:
        """Dispatch inbound bus events by type."""
        msg_type = msg.get("type", "")
        if msg_type == "game_response":
            await self._handle_inbound_response(msg)
        elif msg_type == "room_event":
            await self._handle_inbound_room_event(msg)
        elif msg_type == "broadcast_event":
            await self._handle_inbound_broadcast_event(msg)
        else:
            logger.warning(f"Unknown inbound event type: {msg_type!r}")

    # kept for backward compat (Stage 4 tests reference it directly)
    async def _handle_inbound_response(self, msg: dict) -> None:
        """Handle game_response (direct reply + optional broadcasts)."""
        username = msg.get("username", "")
        room_id = msg.get("room_id", "")
        direct = msg.get("response")
        broadcasts = msg.get("broadcasts", [])

        ws = self._find_ws_by_username(username)
        if ws is not None and direct is not None:
            try:
                await ws.send(direct)
            except Exception as exc:
                logger.warning(f"Could not send direct response to {username!r}: {exc}")

        if broadcasts:
            await self._broadcast_to_room(room_id, broadcasts)

    async def _handle_inbound_room_event(self, msg: dict) -> None:
        """Handle room_event: room_created, room_joined, session_created, reconnected, error."""
        event_type = msg.get("event_type", "")
        username = msg.get("username", "")
        room_id = msg.get("room_id", "")
        payload = msg.get("payload", {})

        ws = self._find_ws_by_username(username)

        if event_type == "error":
            if ws is not None:
                code = payload.get("code", "remote_error")
                err = payload.get("error", "remote error")
                try:
                    await ws.send(make_error(err, code))
                except Exception:
                    pass
            return

        if event_type == "room_created":
            # Store the player→room mapping and room→owner mapping on the gateway.
            # source_server in the room_event envelope is the owner.
            owner_server = msg.get("source_server", "")
            self._store.player_set_room(username, room_id)
            self._store.player_set_color(username, room_id, payload.get("color", "w"))
            if owner_server:
                self._store.room_set_server(room_id, owner_server)
            if ws is not None:
                try:
                    await ws.send(make_room_created(room_id))
                except Exception:
                    pass
            return

        if event_type == "room_joined":
            role = payload.get("role", "player")
            color = payload.get("color")
            game_state = payload.get("game_state")
            owner_server = msg.get("source_server", "")
            self._store.player_set_room(username, room_id)
            if color:
                self._store.player_set_color(username, room_id, color)
            if owner_server:
                self._store.room_set_server(room_id, owner_server)
            if ws is not None:
                messages = [make_room_joined(room_id, color, role)]
                if game_state:
                    messages.append(game_state)
                for m in messages:
                    try:
                        await ws.send(m)
                    except Exception:
                        pass
            return

        if event_type == "session_created":
            match_found = payload.get("match_found")
            game_state = payload.get("game_state")
            color = payload.get("color", "")
            self._store.player_set_room(username, room_id)
            self._store.player_set_color(username, room_id, color)
            if ws is not None:
                for m in [match_found, game_state]:
                    if m:
                        try:
                            await ws.send(m)
                        except Exception:
                            pass
            return

        if event_type == "reconnected":
            login_msg = payload.get("login_success")
            game_state = payload.get("game_state")
            if ws is not None:
                for m in [login_msg, game_state]:
                    if m:
                        try:
                            await ws.send(m)
                        except Exception:
                            pass
            return

    async def _handle_inbound_broadcast_event(self, msg: dict) -> None:
        """Deliver owner-pushed broadcasts to all locally-connected room members."""
        room_id = msg.get("room_id", "")
        broadcasts = msg.get("broadcasts", [])
        await self._broadcast_to_room(room_id, broadcasts)

    async def _broadcast_to_room(self, room_id: str, messages: list[str]) -> None:
        """Send to all locally-connected members of a room."""
        room = self.room_manager.get_room(room_id)
        if room is None:
            # Fall back: any authenticated client whose player_get_room matches
            for ws, info in list(self._authenticated.items()):
                uname = info.get("username", "")
                if self._store.player_get_room(uname) == room_id:
                    for m in messages:
                        try:
                            await ws.send(m)
                        except Exception:
                            pass
            return

        recipients = [
            ws for ws in (list(room.players) + list(room.viewers))
            if not isinstance(ws, _RemoteSender)
        ]
        for ws in recipients:
            for m in messages:
                try:
                    await ws.send(m)
                except Exception:
                    pass

    def _resolve_session_by_room(self, room_id: str) -> "GameSession | None":
        room = self.room_manager.get_room(room_id)
        if room is not None:
            return room.session
        session_id = self._store.room_get_session(room_id)
        if session_id:
            return self.session_manager.get_session_by_id(session_id)
        return None

    # ── Disconnect / cleanup ───────────────────────────────────────────────

    def on_disconnect(self, websocket) -> None:
        """Handle client disconnect."""
        username = self._ws_username.pop(websocket, None)
        if username:
            self._store.matchmaking_remove(username)
            self._store.player_clear_server(username)
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

    # ── Periodic matchmaking ───────────────────────────────────────────────

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
        own_id = self._allocator.own_server_id
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
                    # Always start the game — cross-server path doesn't need ws
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

        p1_server = self._store.player_get_server(username1) or own_id
        p2_server = self._store.player_get_server(username2) or own_id

        # Force cross-server path if either player is not connected locally.
        # This handles the case where allocate_server() returns ourselves but
        # one ws is None (player is on a different server).
        if is_local and (ws1 is None or ws2 is None):
            is_local = False

        if not is_local:
            # Stage 5: publish create_session_cmd to owner
            room_id = uuid.uuid4().hex[:8]
            cmd = make_create_session_cmd(
                source_server=own_id,
                target_server=owner_id,
                room_id=room_id,
                player1_username=username1,
                player1_rating=rating1,
                player1_server=p1_server,
                player2_username=username2,
                player2_rating=rating2,
                player2_server=p2_server,
            )
            await self._bus.publish_async(commands_channel(owner_id), cmd)
            logger.info(
                f"Match delegated to owner {owner_id!r}: "
                f"{username1}@{p1_server} vs {username2}@{p2_server}"
            )
            return

        # Local ownership: create GameSession on this server
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
            self._store.player_set_room(username1, session_id)
            self._store.player_set_room(username2, session_id)
            self._store.room_set_server(session_id, owner_id)
            self._store.room_set_session(session_id, session_id)
            self._store.player_set_server(username1, own_id)
            self._store.player_set_server(username2, own_id)
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

    # ── Reconnect expiry ───────────────────────────────────────────────────

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

    # ── Private message handlers ───────────────────────────────────────────

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

        # Record which server this player is connected to
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
            # Stage 5: session may live on another server
            owner_id = self._store.room_get_server(
                pending.room_id or pending.session_id
            ) if hasattr(pending, "room_id") else None
            own_id = self._allocator.own_server_id
            if owner_id and owner_id != own_id:
                # Forward reconnect to owner
                cmd = make_reconnect_cmd(
                    source_server=own_id,
                    target_server=owner_id,
                    room_id=pending.room_id or pending.session_id,
                    session_id=pending.session_id,
                    username=username,
                    color=pending.color,
                    rating=rating,
                )
                import asyncio
                loop = None
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    pass
                if loop:
                    loop.create_task(
                        self._bus.publish_async(commands_channel(owner_id), cmd)
                    )
                    # Cancel the local reconnect reservation; owner will re-create it
                    self._cancel_reconnect(username)
                    # Response arrives async via room_event
                    return make_login_success(
                        username=username, color=pending.color, rating=rating, reconnected=True
                    )
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
            # Stage 5: publish create_room_cmd to owner, response arrives async
            room_id = uuid.uuid4().hex[:8]
            cmd = make_create_room_cmd(
                source_server=own_id,
                target_server=owner_id,
                room_id=room_id,
                username=auth["username"],
                rating=auth["rating"],
            )
            self._store.player_set_server(auth["username"], own_id)
            try:
                await self._bus.publish_async(commands_channel(owner_id), cmd)
                logger.info(
                    f"create_room forwarded to owner {owner_id!r}: "
                    f"room={room_id!r} user={auth['username']!r}"
                )
            except Exception as exc:
                logger.error(f"create_room_cmd publish failed: {exc}")
                return make_error("could not create room on remote server", "routing_error")
            # Response (room_created) arrives async via room_event handler
            return None  # websocket_server skips None responses

        # Local ownership (unchanged from Stage 4)
        room = self.room_manager.create_room()
        error, role = self.room_manager.join_room(
            room.room_id, sender, auth["username"], auth["rating"]
        )
        if error:
            return make_error(error, error)

        await room.session.start_tick_loop()

        session_id = self.session_manager.get_session_id(room.session)
        if session_id:
            self._store.room_set_server(room.room_id, owner_id)
            self._store.room_set_server(session_id, owner_id)
            self._store.room_set_session(room.room_id, session_id)
            self._store.player_set_room(auth["username"], room.room_id)
            self._store.player_set_server(auth["username"], own_id)
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

        # Stage 5: check if room is on a remote server
        owner_id = self._store.room_get_server(room_id)
        own_id = self._allocator.own_server_id
        if owner_id and owner_id != own_id:
            cmd = make_join_room_cmd(
                source_server=own_id,
                target_server=owner_id,
                room_id=room_id,
                username=auth["username"],
                rating=auth["rating"],
            )
            self._store.player_set_server(auth["username"], own_id)
            try:
                await self._bus.publish_async(commands_channel(owner_id), cmd)
                logger.info(
                    f"join_room forwarded to owner {owner_id!r}: "
                    f"room={room_id!r} user={auth['username']!r}"
                )
            except Exception as exc:
                logger.error(f"join_room_cmd publish failed: {exc}")
                return make_error("could not join room on remote server", "routing_error")
            # Response arrives async via room_event handler
            return None

        # Local path (unchanged from Stage 4)
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

    # ── Internal helpers ───────────────────────────────────────────────────

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


# ── Sentinel object for remote command processing ─────────────────────────────

class _RemoteSender:
    """Placeholder for the 'sender' websocket when processing a forwarded command."""

    def __init__(self, username: str):
        self.username = username

    def __repr__(self) -> str:
        return f"<RemoteSender username={self.username!r}>"

    async def send(self, message: str) -> None:
        """No-op: remote players receive messages via the bus, not directly."""
        pass


# ── Backward-compat shim ──────────────────────────────────────────────────────

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
