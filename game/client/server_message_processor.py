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

    def process_messages(self, messages: list[dict]) -> None:
        """Process up to MAX_MESSAGES_PER_FRAME messages in order."""
        for msg in messages[:MAX_MESSAGES_PER_FRAME]:
            self._handle(msg)

    def _handle(self, msg: dict) -> None:
        msg_type = msg.get("type", "")
        payload = msg.get("payload", {})

        handler = {
            "player_assigned": self._on_player_assigned,
            "game_state": self._on_game_state,
            "move_accepted": self._on_move_accepted,
            "move_rejected": self._on_move_rejected,
            "move_resolved": self._on_move_resolved,
            "jump_accepted": self._on_jump_accepted,
            "jump_rejected": self._on_jump_rejected,
            "game_ended": self._on_game_ended,
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

        if outcome == "captured":
            if gp and gp in self._gm.graphic_pieces:
                self._gm.remove_piece(gp)
        else:
            if gp and final_row is not None and final_col is not None:
                gp.finish_move_at(final_row, final_col)
                if promoted_to:
                    gp.promote_to(promoted_to)

        # Publish MoveResolved for sound/history observers
        if self._event_bus:
            self._event_bus.publish(MoveResolved(
                sequence_id=seq_id or 0,
                piece=piece,
                outcome=outcome or "arrived",
                final_row=final_row,
                final_col=final_col,
                promoted_to=promoted_to,
                captured_piece=captured_piece,
            ))

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
        self._state.game_over = True

        if self._event_bus:
            self._event_bus.publish(GameEnded(winner=winner, loser=loser))

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
