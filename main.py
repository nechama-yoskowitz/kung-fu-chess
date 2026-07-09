from game.parser import parse_input
from game.parser import validate_board
from game.commands import process_commands


def main():
    board, commands = parse_input()

    if not validate_board(board):
        return

    process_commands(board, commands)


if __name__ == "__main__":
    main()
