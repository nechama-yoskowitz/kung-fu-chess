"""
Processes decoded server messages on the main/game thread.

Applies state changes and triggers graphics/sound from authoritative server data.
Contains no WebSocket code. Called once per frame to drain pending messages.
"""

import logging

from game.client.client_game_state import ClientGameState
from game.events import EventBus
from game.events.engine_events import GameEnded, MoveResolved
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.pieces.piece_state_machine import PieceStateMachine
from game.model.constants import DEFAULT_RATING
from game.server.reconnect_manager import RECONNECT_TIMEOUT

logger = logging.getLogger(__name__)

MAX_MESSAGES_PER_FRAME = 20


class ServerMessageProcessor:
    """
    Applies decoded server messages to client state and graphics.

    Call process_messages(messages) once per frame from the game thread.
    """

    def __init__(
        self,
        state: ClientGameState,
        graphics_manager: GraphicsManager,
        event_bus: EventBus | None = None,
        on_shutdown=None,
    ):
        self._state = state
        self._gm = graphics_manager
        self._event_bus = event_bus
        self._on_shutdown = on_shutdown
        # Track active graphic movements by sequence_id
        self._active_movements: dict[int, object] = {}
        # Track source cell for each in-flight move (for board updates on resolve)
        self._move_sources: dict[int, tuple[int, int]] = {}

    def process_messages(self, messages: list[dict]) -> None:
        """Process up to MAX_MESSAGES_PER_FRAME messages in order."""
        for msg in messages[:MAX_MESSAGES_PER_FRAME]:
            self._handle(msg)

    def _handle(self, msg: dict) -> None:
        msg_type = msg.get("type", "")
        payload = msg.get("payload", {})

        handler = {
            "player_assigned": self._on_player_assigned,
            "login_success": self._on_login_success,
            "game_state": self._on_game_state,
            "move_accepted": self._on_move_accepted,
            "move_rejected": self._on_move_rejected,
            "move_resolved": self._on_move_resolved,
            "jump_accepted": self._on_jump_accepted,
            "jump_rejected": self._on_jump_rejected,
            "game_ended": self._on_game_ended,
            "rating_updated": self._on_rating_updated,
            "matchmaking_started": self._on_matchmaking_started,
            "match_found": self._on_match_found,
            "matchmaking_timeout": self._on_matchmaking_timeout,
            "matchmaking_cancelled": self._on_matchmaking_cancelled,
            "room_created": self._on_room_created,
            "room_joined": self._on_room_joined,
            "player_disconnected": self._on_player_disconnected,
            "reconnect_countdown": self._on_reconnect_countdown,
            "player_reconnected": self._on_player_reconnected,
            "error": self._on_error,
            "pong": lambda p: None,
            "raw": lambda p: None,
        }.get(msg_type)

        if handler:
            try:
                handler(payload)
            except Exception as e:
                logger.error(f"Error processing {msg_type}: {e}")
        else:
            logger.warning(f"Unknown message type: {msg_type}")

    def _on_player_assigned(self, payload: dict) -> None:
        color = payload.get("color")
        if color:
            self._state.apply_player_assigned(color)

    def _on_login_success(self, payload: dict) -> None:
        color = payload.get("color", "")
        username = payload.get("username", "")
        rating = payload.get("rating", DEFAULT_RATING)
        self._state.apply_login_success(color or None, username, rating)

    def _on_game_state(self, payload: dict) -> None:
        board = payload.get("board", [])
        clock = payload.get("clock", 0.0)
        white_score = payload.get("white_score", 0)
        black_score = payload.get("black_score", 0)
        game_over = payload.get("game_over", False)

        self._state.apply_game_state(board, clock, white_score, black_score, game_over)
        self._sync_graphics_to_board(board)

    def _on_move_accepted(self, payload: dict) -> None:
        seq_id = payload.get("sequence_id")
        from_row = payload.get("from_row")
        from_col = payload.get("from_col")
        to_row = payload.get("to_row")
        to_col = payload.get("to_col")
        started_at = payload.get("started_at", 0)
        arrive_at = payload.get("arrive_at", 0)

        duration_ms = float(arrive_at - started_at)
        if duration_ms <= 0:
            return

        # Track source cell for board update on resolution
        if seq_id is not None and from_row is not None and from_col is not None:
            self._move_sources[seq_id] = (from_row, from_col)

        gp = self._gm.get_piece_at(from_row, from_col)
        if gp is None:
            return

        if not gp.is_moving:
            gp.start_move(to_row=to_row, to_col=to_col, duration_ms=duration_ms)

        if seq_id is not None:
            self._active_movements[seq_id] = gp

    def _on_move_rejected(self, payload: dict) -> None:
        reason = payload.get("reason", "unknown")
        logger.info(f"Move rejected: {reason}")

    def _on_move_resolved(self, payload: dict) -> None:
        seq_id = payload.get("sequence_id")
        outcome = payload.get("outcome")
        final_row = payload.get("final_row")
        final_col = payload.get("final_col")
        promoted_to = payload.get("promoted_to")
        captured_piece = payload.get("captured_piece")
        piece = payload.get("piece", "")

        gp = self._active_movements.pop(seq_id, None)
        source = self._move_sources.pop(seq_id, None)

        # Step 1: Update the authoritative client board state.
        if source is not None:
            from_row, from_col = source
            self._state.apply_move_resolved(
                from_row=from_row,
                from_col=from_col,
                piece=piece,
                outcome=outcome or "arrived",
                final_row=final_row,
                final_col=final_col,
                promoted_to=promoted_to,
            )

        # Step 2: Update graphics to match the authoritative board.
        if outcome == "captured":
            # The mover itself was captured — remove its GraphicPiece.
            if gp and gp in self._gm.graphic_pieces:
                self._gm.remove_piece(gp)
        else:
            # The mover arrived/stopped — snap it to the final cell.
            if gp and final_row is not None and final_col is not None:
                gp.finish_move_at(final_row, final_col)
                if promoted_to:
                    gp.promote_to(promoted_to)

        # Step 3: Reconcile the destination cell with the authoritative board.
        # This removes any stale GraphicPieces (captured victims, duplicates)
        # that remain at the destination regardless of how they got there.
        if final_row is not None and final_col is not None:
            self._reconcile_cell(final_row, final_col, survivor=gp if outcome != "captured" else None)

        # Step 4: Reconcile the source cell (now empty on the board).
        if source is not None:
            from_row, from_col = source
            self._reconcile_cell(from_row, from_col, survivor=None)

        # Publish MoveResolved for sound/history observers
        if self._event_bus:
            from game.events.engine_events import MoveOutcome
            from game.model.board_adapter import to_domain_piece
            self._event_bus.publish(MoveResolved(
                sequence_id=seq_id or 0,
                piece=to_domain_piece(piece),
                outcome=MoveOutcome(outcome or "arrived"),
                final_row=final_row,
                final_col=final_col,
                promoted_to=to_domain_piece(promoted_to),
                captured_piece=to_domain_piece(captured_piece),
            ))

    def _reconcile_cell(self, row: int, col: int, survivor=None) -> None:
        """
        Ensure graphics at (row, col) match the authoritative board.

        Removes non-moving GraphicPieces that don't match the board token.
        Preserves the `survivor` object (the known-correct mover) even if
        it hasn't been fully snapped yet.
        Preserves any GP still tracked as an active movement (awaiting resolution).
        If survivor is present, all other stationary pieces at the cell are
        removed regardless of token (prevents duplicates from race conditions).
        """
        board = self._state.board
        if not (0 <= row < len(board) and 0 <= col < len(board[0])):
            return

        expected_piece = board[row][col]
        # GPs that are awaiting their own move_resolved should not be removed
        active_gps = set(self._active_movements.values())
        to_remove = []

        for gp in self._gm.get_pieces_at(row, col):
            if gp is survivor:
                continue
            if gp.is_moving:
                continue
            if gp in active_gps:
                continue
            # Stationary GP at this cell — remove if it doesn't belong.
            if expected_piece == "." or gp.piece != expected_piece:
                to_remove.append(gp)
            elif survivor is not None:
                # Board expects this token, but the survivor already represents it.
                # This is a stale duplicate (the old occupant before the mover arrived).
                to_remove.append(gp)

        for gp in to_remove:
            if gp in self._gm.graphic_pieces:
                self._gm.remove_piece(gp)

    def _on_jump_accepted(self, payload: dict) -> None:
        row = payload.get("row")
        col = payload.get("col")
        if row is None or col is None:
            return

        gp = self._gm.get_piece_at(row, col)
        if gp and gp.state != PieceStateMachine.JUMP:
            gp.set_state(PieceStateMachine.JUMP)

    def _on_jump_rejected(self, payload: dict) -> None:
        reason = payload.get("reason", "unknown")
        logger.info(f"Jump rejected: {reason}")

    def _on_game_ended(self, payload: dict) -> None:
        winner = payload.get("winner", "w")
        loser = payload.get("loser", "b")
        reason = payload.get("reason")
        self._state.game_over = True
        self._state.winner_color = winner
        self._state.game_end_reason = reason

        if self._event_bus:
            from game.model.piece import PieceColor
            _STR_TO_COLOR = {"w": PieceColor.WHITE, "b": PieceColor.BLACK}
            self._event_bus.publish(GameEnded(
                winner=_STR_TO_COLOR.get(winner, PieceColor.WHITE),
                loser=_STR_TO_COLOR.get(loser, PieceColor.BLACK),
            ))

    def _on_rating_updated(self, payload: dict) -> None:
        username = payload.get("username")
        new_rating = payload.get("new_rating")
        if username and new_rating is not None:
            self._state.apply_rating_updated(username, new_rating)

    def _on_matchmaking_started(self, payload: dict) -> None:
        """Matchmaking queue entered."""
        self._state.apply_matchmaking_started()

    def _on_match_found(self, payload: dict) -> None:
        """A match was found — store opponent info in state."""
        self._state.apply_match_found(payload)

    def _on_matchmaking_timeout(self, payload: dict) -> None:
        """Matchmaking timed out."""
        self._state.apply_matchmaking_ended()

    def _on_matchmaking_cancelled(self, payload: dict) -> None:
        """Matchmaking was cancelled."""
        self._state.apply_matchmaking_ended()

    def _on_room_created(self, payload: dict) -> None:
        """Room was created — store room ID."""
        room_id = payload.get("room_id", "")
        self._state.apply_room_created(room_id)

    def _on_room_joined(self, payload: dict) -> None:
        """Joined a room — store room info and role."""
        room_id = payload.get("room_id", "")
        role = payload.get("role", "player")
        color = payload.get("color")
        self._state.apply_room_joined(room_id, role, color)

    def _on_player_disconnected(self, payload: dict) -> None:
        """A player disconnected — store for display."""
        username = payload.get("username", "")
        color = payload.get("color", "")
        remaining = payload.get("remaining_seconds", int(RECONNECT_TIMEOUT))
        self._state.apply_player_disconnected(username, color, remaining)

    def _on_reconnect_countdown(self, payload: dict) -> None:
        """Reconnect countdown update."""
        remaining = payload.get("remaining_seconds", 0)
        self._state.apply_reconnect_countdown(remaining)

    def _on_player_reconnected(self, payload: dict) -> None:
        """A player reconnected — clear disconnect state."""
        username = payload.get("username", "")
        self._state.apply_player_reconnected(username)

    def _on_error(self, payload: dict) -> None:
        code = payload.get("code", "")
        message = payload.get("message", "")
        logger.error(f"Server error [{code}]: {message}")

        if code == "game_full" and self._on_shutdown:
            self._on_shutdown()

    def _sync_graphics_to_board(self, board: list[list[str]]) -> None:
        """Rebuild graphics to match the authoritative board without duplicates."""
        # Remove pieces no longer on the board
        to_remove = []
        for gp in self._gm.graphic_pieces:
            if gp.is_moving:
                continue
            if (
                0 <= gp.row < len(board)
                and 0 <= gp.col < len(board[0])
                and board[gp.row][gp.col] == gp.piece
            ):
                continue
            to_remove.append(gp)

        for gp in to_remove:
            self._gm.remove_piece(gp)

        # Add missing pieces
        for r, row in enumerate(board):
            for c, piece in enumerate(row):
                if piece == ".":
                    continue
                existing = self._gm.get_piece_at(r, c)
                if existing and existing.piece == piece:
                    continue
                if existing and existing.piece != piece:
                    # Piece type changed (promotion handled elsewhere)
                    existing.promote_to(piece)
                    continue
                # Create new graphic piece
                from game.graphics.pieces.graphic_piece import GraphicPiece
                gp = GraphicPiece(
                    piece=piece,
                    row=r,
                    col=c,
                    sprite_manager=self._gm.sprite_manager,
                    piece_size=self._gm.piece_size,
                    initial_state="idle",
                )
                self._gm.graphic_pieces.append(gp)
