from game.events.engine_events import MoveOutcome, MoveResolved
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.pieces.piece_state_machine import PieceStateMachine
from game.model.board_adapter import to_legacy_board


class GraphicsSynchronizer:
    """
    One-way synchronization layer: translates engine state and events
    into graphics actions.

    Movement resolution uses the Observer pattern (MoveResolved events)
    for unambiguous outcome handling. Jump and cooldown state are polled
    per frame because they are simple presence/absence checks.
    """

    def __init__(self, graphics_manager: GraphicsManager, event_bus=None):
        self.graphics_manager = graphics_manager
        self._synced_sequence_ids: set[int] = set()
        # Maps sequence_id → GraphicPiece for in-flight movements
        self._active_movements: dict[int, object] = {}
        # Tracks currently jumping cells as (row, col) → GraphicPiece
        self._active_jumps: dict[tuple[int, int], object] = {}

        if event_bus:
            event_bus.subscribe(MoveResolved, self._handle_move_resolved)

    def initialize(self, board) -> None:
        """Read the current board state and populate the graphics layer."""
        self.graphics_manager.initialize_from_board(to_legacy_board(board))
        self._synced_sequence_ids.clear()
        self._active_movements.clear()
        self._active_jumps.clear()

    def sync_movements(self, pending_moves) -> None:
        """
        Detect newly created PendingMove objects and start graphic animations.

        Uses sequence_id to ensure each movement is started exactly once.
        """
        for move in pending_moves:
            if move.sequence_id in self._synced_sequence_ids:
                continue

            self._synced_sequence_ids.add(move.sequence_id)

            graphic_piece = self.graphics_manager.get_piece_at(
                move.from_row, move.from_col
            )

            if graphic_piece is None:
                continue

            duration_ms = float(move.arrive_at - move.started_at)

            if duration_ms <= 0:
                continue

            graphic_piece.start_move(
                to_row=move.to_row,
                to_col=move.to_col,
                duration_ms=duration_ms,
            )

            self._active_movements[move.sequence_id] = graphic_piece

    def sync_jumps(self, active_jumps) -> None:
        """
        Synchronize engine ActiveJump state with graphic piece animations.

        Uses (row, col) as association key — safe because the engine
        prevents a piece from jumping if already airborne.
        """
        engine_jumping = {(j.row, j.col) for j in active_jumps}

        for jump in active_jumps:
            key = (jump.row, jump.col)
            if key in self._active_jumps:
                continue

            gp = self.graphics_manager.get_piece_at(jump.row, jump.col)
            if gp is None:
                continue

            gp.set_state(PieceStateMachine.JUMP)
            self._active_jumps[key] = gp

        expired_keys = [
            key for key in self._active_jumps
            if key not in engine_jumping
        ]

        for key in expired_keys:
            gp = self._active_jumps.pop(key)
            if gp in self.graphics_manager.graphic_pieces:
                if gp.state == PieceStateMachine.JUMP:
                    gp.set_state(PieceStateMachine.IDLE)

    def sync_removals(self, board) -> None:
        """
        Remove stationary graphic pieces that were captured.

        A non-moving piece whose board cell no longer contains its token
        was captured by an arriving enemy. Moving pieces are handled by
        MoveResolved events, not by this method.
        """
        from game.model.board_adapter import to_legacy_piece
        to_remove = []
        for gp in self.graphics_manager.graphic_pieces:
            if gp.is_moving:
                continue

            if (
                0 <= gp.row < len(board)
                and 0 <= gp.col < len(board[0])
                and to_legacy_piece(board[gp.row][gp.col]) == gp.piece
            ):
                continue

            to_remove.append(gp)

        for gp in to_remove:
            self.graphics_manager.remove_piece(gp)

    def _handle_move_resolved(self, event: MoveResolved) -> None:
        """
        React to an authoritative MoveResolved event from the engine.

        Uses sequence_id to find the exact GraphicPiece — no board scanning
        or token matching needed.
        """
        gp = self._active_movements.pop(event.sequence_id, None)
        if gp is None:
            return

        if event.outcome == MoveOutcome.CAPTURED:
            if gp in self.graphics_manager.graphic_pieces:
                self.graphics_manager.remove_piece(gp)
            return

        # Arrived or stopped — snap to authoritative final cell.
        if event.final_row is not None and event.final_col is not None:
            gp.finish_move_at(event.final_row, event.final_col)

        # Promotion — update piece token and reload animation.
        if event.promoted_to:
            from game.model.board_adapter import to_legacy_piece
            gp.promote_to(to_legacy_piece(event.promoted_to))

    @staticmethod
    def get_cooldown_indicators(active_cooldowns, clock, cooldown_duration_ms):
        """
        Compute cooldown progress for each active cooldown.

        Returns list of (row, col, progress) where progress is 1.0 at
        cooldown start and 0.0 at expiry.
        """
        indicators = []

        for cd in active_cooldowns:
            remaining = cd.available_at - clock
            if remaining <= 0:
                continue

            progress = min(remaining / cooldown_duration_ms, 1.0)
            indicators.append((cd.row, cd.col, progress))

        return indicators
