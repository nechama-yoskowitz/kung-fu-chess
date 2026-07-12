from game.io.parser import (
    parse_input,
    validate_board,
)

from game.io.command_runner import process_commands

def main():
    board, commands = parse_input()

    if not validate_board(board):
        return

    process_commands(board, commands)


if __name__ == "__main__":
    main()
