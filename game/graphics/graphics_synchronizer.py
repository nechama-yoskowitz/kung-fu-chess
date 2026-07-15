from game.graphics.graphics_manager import GraphicsManager


class GraphicsSynchronizer:
    """
    One-way synchronization layer: reads state from the game engine
    and drives the graphics layer accordingly.

    This class lives in the graphics layer and depends on the engine's
    public attributes (board, pending_moves). The engine has no knowledge
    of this class or any graphics types.

    Current scope:
    - Initial board setup.
    - Movement synchronization (new PendingMoves trigger graphic animations).
    - Capture/arrival synchronization (resolved moves update or remove pieces).
    """

    def __init__(self, graphics_manager: GraphicsManager):
        self.graphics_manager = graphics_manager
        self._synced_sequence_ids: set[int] = set()
        # Maps sequence_id → (GraphicPiece, to_row, to_col, piece_token)
        self._active_movements: dict[int, tuple] = {}

    def initialize(self, board) -> None:
        """
        Read the current board state and populate the graphics layer.

        Parameters
        ----------
        board : list[list[str]]
            The engine's board matrix.
        """
        self.graphics_manager.initialize_from_board(board)
        self._synced_sequence_ids.clear()
        self._active_movements.clear()

    def sync_movements(self, pending_moves) -> None:
        """
        Detect newly created PendingMove objects and start the
        corresponding graphic piece animations.

        Each PendingMove is identified by its unique sequence_id.
        Once a movement has been started on the graphics side, its
        sequence_id is recorded so it is never triggered again.
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

            # Track this active movement so we can resolve its outcome later.
            self._active_movements[move.sequence_id] = (
                graphic_piece,
                move.to_row,
                move.to_col,
                move.piece,
            )

    def sync_removals(self, board, pending_moves) -> None:
        """
        Reconcile graphic pieces with the engine's authoritative state.

        Two concerns are handled:

        1. Resolved movements: A previously-active movement whose
           sequence_id is no longer in pending_moves has been resolved
           by the engine. We check the board to determine the outcome:
           - Arrived/stopped: board contains the piece at its destination
             (or another valid cell). Snap the graphic piece there.
           - Captured: board does NOT contain the piece at the destination.
             Remove the graphic piece.

        2. Stationary captures: A non-moving graphic piece whose board
           cell no longer contains its token was captured by another piece.
        """
        # Build set of currently active sequence_ids in the engine.
        active_seq_ids = {move.sequence_id for move in pending_moves}

        # --- Resolve completed movements ---
        resolved_ids = [
            seq_id for seq_id in self._active_movements
            if seq_id not in active_seq_ids
        ]

        for seq_id in resolved_ids:
            gp, to_row, to_col, piece_token = self._active_movements.pop(seq_id)

            # Check if the piece arrived at its intended destination.
            if (
                0 <= to_row < len(board)
                and 0 <= to_col < len(board[0])
                and board[to_row][to_col] == piece_token
            ):
                # Arrived successfully.
                gp.finish_move_at(to_row, to_col)
                continue

            # Check if the piece was stopped at another cell.
            # The engine places stopped pieces on the board. Search for a
            # cell containing this piece token that isn't already claimed
            # by another graphic piece.
            found_cell = self._find_piece_on_board(
                board, piece_token, gp
            )

            if found_cell is not None:
                # Piece was stopped at this cell.
                gp.finish_move_at(found_cell[0], found_cell[1])
                continue

            # Piece is not on the board anywhere → captured.
            self.graphics_manager.remove_piece(gp)

        # --- Remove stationary pieces that were captured ---
        to_remove = []
        for gp in self.graphics_manager.graphic_pieces:
            # Skip pieces with active tracked movements — they are handled above.
            if gp.is_moving:
                continue

            if (
                0 <= gp.row < len(board)
                and 0 <= gp.col < len(board[0])
                and board[gp.row][gp.col] == gp.piece
            ):
                continue

            # Not on the board at its logical position → captured.
            to_remove.append(gp)

        for gp in to_remove:
            self.graphics_manager.remove_piece(gp)

    def _find_piece_on_board(self, board, piece_token, exclude_gp):
        """
        Search the board for a cell containing piece_token that isn't
        already claimed by another (non-excluded) graphic piece.

        Returns (row, col) if found, None otherwise.
        """
        # Collect cells already occupied by other graphic pieces of the same token.
        claimed = set()
        for other_gp in self.graphics_manager.graphic_pieces:
            if other_gp is exclude_gp:
                continue
            if other_gp.piece == piece_token and not other_gp.is_moving:
                claimed.add((other_gp.row, other_gp.col))

        for r in range(len(board)):
            for c in range(len(board[0])):
                if board[r][c] == piece_token and (r, c) not in claimed:
                    return (r, c)

        return None
