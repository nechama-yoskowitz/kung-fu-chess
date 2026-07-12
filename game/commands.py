from game.board_printer import print_board
from game.engine.game_engine import GameEngine
from game.input.controller import Controller


def process_commands(board, commands):
    """Parse text commands and delegate them to the game layers."""
    engine = GameEngine(board)
    controller = Controller(board)

    for command in commands:
        parts = command.split()

        if command == "print board":
            if not engine.game_over:
                engine.update_game_state()

            print_board(board)

        elif parts[0] == "click":
            if engine.game_over:
                continue

            x = int(parts[1])
            y = int(parts[2])

            new_move = controller.click(
                engine.pending_moves,
                x,
                y,
                engine.clock,
            )

            if new_move is not None:
                engine.pending_moves.append(new_move)

        elif parts[0] == "jump":
            if engine.game_over:
                continue

            x = int(parts[1])
            y = int(parts[2])

            new_jump = controller.jump(
                engine.pending_moves,
                engine.active_jumps,
                x,
                y,
                engine.clock,
            )

            if new_jump is not None:
                engine.active_jumps.append(new_jump)

        elif parts[0] == "wait":
            ms = int(parts[1])
            engine.handle_wait(ms)