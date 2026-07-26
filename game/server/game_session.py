"""
Server-side game session — bridges WebSocket clients to a single GameEngine.

Async model:
- Engine EventBus callbacks are synchronous. They queue outgoing messages.
- The server's async code drains the queue and awaits real WebSocket sends.
- This avoids mixing sync/async and eliminates coroutine warnings.
"""

import asyncio
import json
import logging
from collections import deque

from game.engine.game_engine import GameEngine
from game.events.engine_events import GameEnded, MoveResolved
from game.model.pieces import get_color
from game.server.protocol import (
    decode_message,
    encode_message,
    make_error,
    make_game_ended,
    make_game_state,
    make_jump_accepted,
    make_jump_rejected,
    make_login_success,
    make_move_accepted,
    make_move_rejected,
    make_move_resolved,
    make_pong,
    validate_jump_request,
    validate_move_request,
)

logger = logging.getLogger(__name__)

STARTING_BOARD = [
    ["bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"],
    ["bP", "bP", "bP", "bP", "bP", "bP", "bP", "bP"],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    ["wP", "wP", "wP", "wP", "wP", "wP", "wP", "wP"],
    ["wR", "wN", "wB", "wQ", "wK", "wB", "wN", "wR"],
]

TICK_INTERVAL_MS = 50
MAX_PLAYERS = 2


class GameSession:
    """
    Manages one active game with login, player assignment, and ownership validation.

    A client must send a login_request before being assigned a color or allowed
    to send move/jump requests.
    """

    def __init__(self, board=None):
        self._board = board or [row[:] for row in STARTING_BOARD]
        self.engine = GameEngine(self._board)
        self._clients: set = set()
        self._player_colors: dict = {}  # websocket → "w" | "b"
        self._player_usernames: dict = {}  # websocket → username
        self._viewers: set = set()  # websockets that are spectating
        self._tick_task: asyncio.Task | None = None
        # Queue for messages produced by synchronous EventBus callbacks.
        self._outbox: deque[str] = deque()

        self.engine.event_bus.subscribe(MoveResolved, self._on_move_resolved)
        self.engine.event_bus.subscribe(GameEnded, self._on_game_ended)

    # ─── Client management ────────────────────────────────────────────────

    def add_client(self, websocket) -> None:
        """
        Register a WebSocket connection. Does NOT assign a color yet.

        The client must send a login_request to be assigned a color and
        receive the game state.
        """
        self._clients.add(websocket)

    def login_client(self, websocket, username: str, rating: int = 1200) -> list[str]:
        """
        Attempt to log in a connected client with the given username.

        Returns a list of messages to send to this client:
        - On success: login_success + game_state
        - On failure: error message (username_in_use or game_full)
        """
        messages = []

        # Already logged in — ignore duplicate login
        if websocket in self._player_colors:
            messages.append(make_error("already logged in", "already_logged_in"))
            return messages

        # Duplicate username check (already-connected user with same name)
        active_usernames = set(self._player_usernames.values())
        if username in active_usernames:
            messages.append(make_error(
                f"username '{username}' is already connected", "username_in_use"
            ))
            return messages

        # Assign color
        color = self._assign_color(websocket)
        if color is None:
            messages.append(make_error("game is full", "game_full"))
            return messages

        self._player_usernames[websocket] = username
        messages.append(make_login_success(username=username, color=color, rating=rating))
        messages.append(self._make_game_state())
        return messages

    def remove_client(self, websocket) -> None:
        """Unregister a client and free their color and username."""
        self._clients.discard(websocket)
        self._viewers.discard(websocket)
        if websocket in self._player_colors:
            del self._player_colors[websocket]
        if websocket in self._player_usernames:
            del self._player_usernames[websocket]

    def add_viewer(self, websocket) -> None:
        """Add a client as a viewer (spectator). Receives broadcasts but cannot play."""
        self._clients.add(websocket)
        self._viewers.add(websocket)

    def is_viewer(self, websocket) -> bool:
        """Return True if the websocket is a viewer."""
        return websocket in self._viewers

    def is_full(self) -> bool:
        """True if both player slots are taken."""
        return len(self._player_colors) >= MAX_PLAYERS

    def is_logged_in(self, websocket) -> bool:
        """True if the client has completed the login handshake (player or viewer)."""
        return websocket in self._player_colors or websocket in self._viewers

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def get_player_color(self, websocket) -> str | None:
        """Return the assigned color for a client, or None."""
        return self._player_colors.get(websocket)

    def get_player_username(self, websocket) -> str | None:
        """Return the username for a client, or None."""
        return self._player_usernames.get(websocket)

    # ─── Message handling ─────────────────────────────────────────────────

    async def handle_message(self, raw: str, sender) -> str | list[str] | None:
        """
        Process a protocol message. Returns a direct response to the sender
        (str or list of str), or None if only broadcasts were queued.

        After calling this, the caller must call drain_outbox() to send
        any queued broadcast messages.
        """
        msg = decode_message(raw)

        if msg is None:
            # Legacy unstructured text
            if not raw or not raw.strip():
                return make_error("empty_message")
            stripped = raw.strip()
            if stripped == "ping":
                return "pong"
            return json.dumps({"type": "echo", "payload": stripped})

        msg_type = msg.get("type", "")
        payload = msg.get("payload", {})

        if msg_type == "ping":
            return make_pong()

        # All gameplay messages require login
        if not self.is_logged_in(sender):
            return make_error("must login first", "not_logged_in")

        # Viewers cannot perform gameplay actions
        if self.is_viewer(sender):
            return make_error("viewers cannot perform actions", "viewer_action_forbidden")

        if msg_type == "move_request":
            return self._handle_move_request(payload, sender)

        if msg_type == "jump_request":
            return self._handle_jump_request(payload, sender)

        return make_error(f"unknown message type: {msg_type}", "unknown_type")

    # ─── Time ─────────────────────────────────────────────────────────────

    def tick(self, delta_ms: float) -> None:
        """Advance the engine clock. Queues any broadcast messages."""
        if not self.engine.game_over:
            self.engine.handle_wait(delta_ms)

    async def start_tick_loop(self) -> None:
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def stop_tick_loop(self) -> None:
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass

    # ─── Outbox (sync → async bridge) ────────────────────────────────────

    async def drain_outbox(self) -> None:
        """Send all queued broadcast messages to connected clients."""
        while self._outbox:
            message = self._outbox.popleft()
            await self._broadcast_async(message)

    def get_pending_broadcasts(self) -> list[str]:
        """Pop all queued messages (for synchronous test inspection)."""
        msgs = list(self._outbox)
        self._outbox.clear()
        return msgs

    # ─── Private ──────────────────────────────────────────────────────────

    def _assign_color(self, websocket) -> str | None:
        """Assign the next available color, or None if full."""
        taken = set(self._player_colors.values())
        if "w" not in taken:
            self._player_colors[websocket] = "w"
            return "w"
        if "b" not in taken:
            self._player_colors[websocket] = "b"
            return "b"
        return None

    def _handle_move_request(self, payload: dict, sender) -> str:
        error = validate_move_request(payload)
        if error:
            return make_error(error, "validation_error")

        from_row = payload["from_row"]
        from_col = payload["from_col"]
        to_row = payload["to_row"]
        to_col = payload["to_col"]

        # Ownership check: player can only move their own pieces.
        ownership_error = self._check_ownership(sender, from_row, from_col)
        if ownership_error:
            return ownership_error

        result = self.engine.request_move(from_row, from_col, to_row, to_col)

        if not result.is_accepted:
            return make_move_rejected(result.reason, from_row, from_col, to_row, to_col)

        pm = self.engine.pending_moves[-1]
        accepted_msg = make_move_accepted(
            sequence_id=pm.sequence_id,
            piece=pm.piece,
            from_row=pm.from_row,
            from_col=pm.from_col,
            to_row=pm.to_row,
            to_col=pm.to_col,
            started_at=pm.started_at,
            arrive_at=pm.arrive_at,
        )

        self._queue_broadcast(accepted_msg)
        return None

    def _handle_jump_request(self, payload: dict, sender) -> str:
        error = validate_jump_request(payload)
        if error:
            return make_error(error, "validation_error")

        row = payload["row"]
        col = payload["col"]

        # Ownership check
        ownership_error = self._check_ownership(sender, row, col)
        if ownership_error:
            return ownership_error

        accepted = self.engine.request_jump(row, col)

        if not accepted:
            return make_jump_rejected("invalid_jump", row, col)

        jump = self.engine.active_jumps[-1]
        accepted_msg = make_jump_accepted(
            piece=jump.piece,
            row=jump.row,
            col=jump.col,
            expires_at=jump.expires_at,
        )

        self._queue_broadcast(accepted_msg)
        return None

    def _check_ownership(self, sender, row: int, col: int) -> str | None:
        """
        Verify the sender owns the piece at (row, col).
        Returns an error message string if ownership fails, None if OK.
        """
        player_color = self._player_colors.get(sender)
        if player_color is None:
            return make_move_rejected("not_assigned", row, col, row, col)

        board = self.engine.legacy_board
        if 0 <= row < len(board) and 0 <= col < len(board[0]):
            piece = board[row][col]
            if piece != "." and get_color(piece) != player_color:
                return make_move_rejected("not_your_piece", row, col, row, col)

        return None

    def _on_move_resolved(self, event: MoveResolved) -> None:
        """Queue a move_resolved broadcast (synchronous EventBus callback)."""
        msg = make_move_resolved(
            sequence_id=event.sequence_id,
            piece=event.piece,
            outcome=event.outcome,
            final_row=event.final_row,
            final_col=event.final_col,
            promoted_to=event.promoted_to,
            captured_piece=event.captured_piece,
        )
        self._queue_broadcast(msg)

    def _on_game_ended(self, event: GameEnded) -> None:
        """Queue a game_ended broadcast (synchronous EventBus callback)."""
        msg = make_game_ended(winner=event.winner, loser=event.loser)
        self._queue_broadcast(msg)

    def _make_game_state(self) -> str:
        return make_game_state(
            board=self.engine.legacy_board,
            clock=self.engine.clock,
            white_score=self.engine.white_score,
            black_score=self.engine.black_score,
            game_over=self.engine.game_over,
        )

    def _queue_broadcast(self, message: str) -> None:
        """Add a message to the outbox for later async delivery."""
        self._outbox.append(message)

    async def _broadcast_async(self, message: str) -> None:
        """Send a message to all connected clients (players and viewers)."""
        if not self._clients:
            return

        # Broadcast to players and viewers
        recipients = [c for c in self._clients if c in self._player_colors or c in self._viewers]
        if not recipients:
            return

        results = await asyncio.gather(
            *[client.send(message) for client in recipients],
            return_exceptions=True,
        )

        # Remove clients that failed
        failed = set()
        for client, result in zip(recipients, results):
            if isinstance(result, Exception):
                failed.add(client)

        for client in failed:
            self._clients.discard(client)
            if client in self._player_colors:
                del self._player_colors[client]
            if client in self._player_usernames:
                del self._player_usernames[client]

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(TICK_INTERVAL_MS / 1000)
            self.tick(TICK_INTERVAL_MS)
            await self.drain_outbox()
