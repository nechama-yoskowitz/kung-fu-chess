"""
Legacy text-mode entry point for the original Kung-Fu Chess assignment.

Reads a board and move commands from stdin, processes them, and prints results.
This interface is NOT used by the graphical or network modes.
Use run_game.py for the graphical game or python -m game.server for the server.
"""

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
