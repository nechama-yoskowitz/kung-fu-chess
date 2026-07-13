from game.model.constants import (
    EMPTY_CELL,
    MOVE_DURATION_MS,
    PIECE_QUEEN,
)
from game.model.pieces import get_color, is_king, is_pawn, make_piece, same_color
from game.realtime.motion import (
    compute_path,
    decompose_moves_to_events,
    get_airborne_piece_at,
)
from game.rules.rules import pawn_promotion_row


def expire_jumps(active_jumps, clock):
    """Return only jumps that have not expired yet."""
    return [
        jump
        for jump in active_jumps
        if jump.expires_at >= clock
    ]


def _current_virtual_cell(move, clock):
    """
    Compute the virtual cell a move occupies at the given clock time.

    If the move hasn't started yet, returns the source cell.
    If the move has arrived, returns the destination.
    Otherwise, returns the last cell reached by the given clock.
    """
    if clock < move.started_at:
        return (move.from_row, move.from_col)

    path = compute_path(move.piece, move.from_row, move.from_col, move.to_row, move.to_col)
    path_len = len(path)

    for i, (r, c) in enumerate(path):
        if path_len == 1:
            cell_time = move.arrive_at
        else:
            cell_time = move.started_at + (i + 1) * MOVE_DURATION_MS

        if cell_time > clock:
            # Haven't reached this cell yet
            if i == 0:
                return (move.from_row, move.from_col)
            return path[i - 1]

    return path[-1]


def apply_arrived_moves(board, pending_moves, clock, active_jumps=None):
    """
    Resolve pending moves using event-based chronological processing.

    This function processes all events in the window (0, clock] for moves
    whose arrive_at <= clock, using virtual occupancy to detect collisions.

    For backward compatibility, this is called with clock = current_clock
    by the arbiter's update_state, which manages the windowing.

    Returns:
        (still_pending, game_over, active_jumps, arrived_cells)
    """
    if active_jumps is None:
        active_jumps = []

    return _resolve_window(board, pending_moves, 0, clock, active_jumps)


def resolve_window(board, pending_moves, prev_clock, curr_clock, active_jumps):
    """
    Resolve events in the time window (prev_clock, curr_clock].

    This is the primary entry point for event-based resolution.

    Returns:
        (still_pending, game_over, active_jumps, arrived_cells)
    """
    return _resolve_window(board, pending_moves, prev_clock, curr_clock, active_jumps)


def _resolve_window(board, pending_moves, prev_clock, curr_clock, active_jumps):
    """
    Internal event-based resolution.

    Returns:
        (still_pending, game_over, active_jumps, arrived_cells)
    """
    if not pending_moves:
        return [], False, active_jumps, []

    # Generate all events and filter to the current window
    all_events = decompose_moves_to_events(pending_moves)
    
    # A move whose arrive_at <= curr_clock should have ALL its events processed
    # (even intermediate ones whose computed time might be > curr_clock due to
    #  test-created PendingMoves with artificial arrive_at values).
    # A move whose arrive_at > curr_clock only has events up to curr_clock processed.
    completed_seq_ids = {
        move.sequence_id for move in pending_moves if move.arrive_at <= curr_clock
    }
    
    relevant_events = [
        e for e in all_events
        if (prev_clock < e.event_time <= curr_clock)
        or (e.sequence_id in completed_seq_ids and e.event_time > prev_clock)
    ]

    # Build initial virtual occupancy
    # - Static board pieces (not sources of active moves)
    # - Moving pieces at their virtual position as of prev_clock
    moving_sources = set()
    for move in pending_moves:
        moving_sources.add((move.from_row, move.from_col))

    # occupancy: (row, col) → {"piece": str, "seq_id": int|None, "airborne": bool}
    occupancy = {}

    for r in range(len(board)):
        for c in range(len(board[0])):
            if (r, c) in moving_sources:
                continue
            if board[r][c] != EMPTY_CELL:
                occupancy[(r, c)] = {"piece": board[r][c], "seq_id": None, "airborne": False}

    # Add airborne pieces
    for jump in active_jumps:
        if jump.expires_at > prev_clock:
            occupancy[(jump.row, jump.col)] = {
                "piece": jump.piece, "seq_id": None, "airborne": True,
                "expires_at": jump.expires_at,
            }

    # Track move status and final positions
    move_status = {move.sequence_id: "active" for move in pending_moves}
    move_final_cell = {}
    move_prev_cell = {}

    # Add moving pieces at their virtual positions
    for move in pending_moves:
        # If the piece is not at its source on the board, the move is invalid
        if board[move.from_row][move.from_col] != move.piece:
            move_status[move.sequence_id] = "captured"  # pre-cancel
            continue
        vc = _current_virtual_cell(move, prev_clock)
        if vc not in occupancy:
            occupancy[vc] = {"piece": move.piece, "seq_id": move.sequence_id, "airborne": False}
        else:
            existing = occupancy[vc]
            if existing.get("seq_id") is not None:
                occupancy[vc] = {"piece": move.piece, "seq_id": move.sequence_id, "airborne": False}

    # Initialize prev_cell for each move
    for move in pending_moves:
        if move_status[move.sequence_id] == "active":
            move_prev_cell[move.sequence_id] = _current_virtual_cell(move, prev_clock)

    captured_static_cells = []  # cells where static pieces were captured
    game_over = False
    game_over_time = None

    # Process events chronologically
    for event in relevant_events:
        seq_id = event.sequence_id

        if move_status[seq_id] != "active":
            continue

        if game_over:
            continue

        target = (event.row, event.col)
        prev_cell = move_prev_cell[seq_id]

        # Check if airborne piece at target has expired by this event's time
        occupant = occupancy.get(target)
        if occupant and occupant.get("airborne"):
            if occupant.get("expires_at", 0) < event.event_time:
                # Jump expired before this event — remove from occupancy
                del occupancy[target]
                occupant = None

        # Remove piece from its previous virtual cell
        if prev_cell in occupancy and occupancy[prev_cell].get("seq_id") == seq_id:
            del occupancy[prev_cell]

        # Re-check occupant at target (may have changed)
        occupant = occupancy.get(target)

        if occupant is None:
            # Empty cell — piece moves in
            occupancy[target] = {"piece": event.piece, "seq_id": seq_id, "airborne": False}
            move_prev_cell[seq_id] = target
            if event.is_final:
                move_status[seq_id] = "arrived"
                move_final_cell[seq_id] = target

        elif occupant.get("airborne") and get_color(occupant["piece"]) != get_color(event.piece):
            # Airborne ENEMY — arriving piece is destroyed
            move_status[seq_id] = "captured"

        elif occupant.get("airborne") and get_color(occupant["piece"]) == get_color(event.piece):
            # Airborne FRIENDLY — treat as empty (airborne piece is "in the air")
            occupancy[target] = {"piece": event.piece, "seq_id": seq_id, "airborne": False}
            move_prev_cell[seq_id] = target
            if event.is_final:
                move_status[seq_id] = "arrived"
                move_final_cell[seq_id] = target

        elif same_color(occupant["piece"], event.piece):
            # Same color ground piece — STOP at previous cell
            move_status[seq_id] = "stopped"
            if prev_cell and prev_cell != (None, None):
                move_final_cell[seq_id] = prev_cell
                occupancy[prev_cell] = {"piece": event.piece, "seq_id": seq_id, "airborne": False}
            else:
                move_final_cell[seq_id] = None

        else:
            # Opposite color ground piece — CAPTURE the occupant
            captured_piece = occupant["piece"]

            if occupant["seq_id"] is not None:
                move_status[occupant["seq_id"]] = "captured"
            else:
                captured_static_cells.append(target)

            if is_king(captured_piece):
                game_over = True
                game_over_time = event.event_time

            occupancy[target] = {"piece": event.piece, "seq_id": seq_id, "airborne": False}
            move_prev_cell[seq_id] = target
            if event.is_final:
                move_status[seq_id] = "arrived"
                move_final_cell[seq_id] = target

    # --- Apply results to board ---
    arrived_cells = []

    # Phase 1: Clear sources of all non-active moves
    for move in pending_moves:
        status = move_status[move.sequence_id]
        if status in ("arrived", "stopped", "captured"):
            if board[move.from_row][move.from_col] == move.piece:
                board[move.from_row][move.from_col] = EMPTY_CELL

    # Phase 2: Clear captured static cells
    for (r, c) in captured_static_cells:
        if (r, c) not in move_final_cell.values():
            board[r][c] = EMPTY_CELL

    # Phase 3: Place arrived/stopped pieces
    for move in pending_moves:
        status = move_status[move.sequence_id]
        if status in ("arrived", "stopped"):
            final = move_final_cell.get(move.sequence_id)
            if final:
                fr, fc = final
                board[fr][fc] = move.piece
                # Promotion
                if is_pawn(move.piece):
                    color = get_color(move.piece)
                    if fr == pawn_promotion_row(board, color):
                        board[fr][fc] = make_piece(color, PIECE_QUEEN)
                landed_piece = board[fr][fc]
                arrived_cells.append((landed_piece, fr, fc))

    # Build remaining pending_moves (only ACTIVE ones)
    still_pending = [
        move for move in pending_moves
        if move_status[move.sequence_id] == "active"
    ]

    if game_over:
        still_pending = []

    return still_pending, game_over, active_jumps, arrived_cells
