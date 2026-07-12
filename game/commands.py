from game.board_printer import print_board
from game.input.controller import Controller
from game.movement import apply_arrived_moves, expire_jumps


def handle_wait(clock, ms):
    """Advance the game clock by ms milliseconds."""
    return clock + ms


def _update_game_state(board, pending_moves, active_jumps, clock):
    """
    Update all time-dependent game state.

    - Remove expired jumps.
    - Apply moves that reached their destination.
    - Clear remaining actions if the game ended.

    Returns:
        (pending_moves, active_jumps, game_over)
    """
    active_jumps = expire_jumps(active_jumps, clock)

    pending_moves, game_over, active_jumps = apply_arrived_moves(
        board,
        pending_moves,
        clock,
        active_jumps,
    )

    if game_over:
        pending_moves = []
        active_jumps = []

    return pending_moves, active_jumps, game_over


def process_commands(board, commands):
    """Parse and execute text commands against the game."""
    controller = Controller(board)

    clock = 0
    pending_moves = []
    active_jumps = []
    game_over = False

    for command in commands:
        parts = command.split()

        if command == "print board":
            if not game_over:
                pending_moves, active_jumps, game_over = _update_game_state(
                    board,
                    pending_moves,
                    active_jumps,
                    clock,
                )

            print_board(board)

        elif parts[0] == "click":
            if game_over:
                continue

            x = int(parts[1])
            y = int(parts[2])

            new_move = controller.click(
                pending_moves,
                x,
                y,
                clock,
            )

            if new_move is not None:
                pending_moves.append(new_move)

        elif parts[0] == "jump":
            if game_over:
                continue

            x = int(parts[1])
            y = int(parts[2])

            new_jump = controller.jump(
                pending_moves,
                active_jumps,
                x,
                y,
                clock,
            )

            if new_jump is not None:
                active_jumps.append(new_jump)

        elif parts[0] == "wait":
            ms = int(parts[1])
            clock = handle_wait(clock, ms)

            if not game_over:
                pending_moves, active_jumps, game_over = _update_game_state(
                    board,
                    pending_moves,
                    active_jumps,
                    clock,
                )