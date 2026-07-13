import sys

from game.io.parser import GameInputParser, validate_board
from game.io.command_runner import process_commands


def main():
    parser = GameInputParser()
    board, commands = parser.parse(sys.stdin)

    if not validate_board(board):
        return

    process_commands(board, commands)


if __name__ == "__main__":
    main()
