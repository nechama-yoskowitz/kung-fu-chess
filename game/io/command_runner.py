from game.io.board_printer import print_board
from game.engine.game_engine import GameEngine
from game.controller.controller import Controller


def process_commands(board, commands):
    """Parse text commands and delegate them to the game layers."""

    engine = GameEngine(board)
    controller = Controller(engine)

    for command in commands:
        parts = command.split()

        if command == "print board":
            if not engine.game_over:
                engine.update_game_state()

            print_board(engine.legacy_board)

        elif parts[0] == "click":
            if engine.game_over:
                continue

            x = int(parts[1])
            y = int(parts[2])

            controller.click(x, y)

        elif parts[0] == "jump":
            if engine.game_over:
                continue

            x = int(parts[1])
            y = int(parts[2])

            controller.jump(x, y)

        elif parts[0] == "wait":
            ms = int(parts[1])
            engine.handle_wait(ms)