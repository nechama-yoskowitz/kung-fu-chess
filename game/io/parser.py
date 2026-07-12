import sys

from game.model.constants import (
    VALID_TOKENS,
    ERROR_ROW_WIDTH_MISMATCH,
    ERROR_UNKNOWN_TOKEN,
)


_SECTION_BOARD    = "Board:"
_SECTION_COMMANDS = "Commands:"


def parse_input():
    """
    Read stdin and return (board, commands).
    board    — list of rows, each row a list of token strings
    commands — list of non-empty command strings
    """
    lines = sys.stdin.read().splitlines()

    board_lines   = []
    command_lines = []

    in_board    = False
    in_commands = False

    for raw_line in lines:
        line = raw_line.strip()

        if line == _SECTION_BOARD:
            in_board    = True
            in_commands = False
            continue

        if line == _SECTION_COMMANDS:
            in_board    = False
            in_commands = True
            continue

        if in_board:
            board_lines.append(line)
        elif in_commands and line:
            command_lines.append(line)

    board = [line.split() for line in board_lines]

    return board, command_lines

def validate_board(board):
    """
    Validate that all rows have equal width and all tokens are known.
    Prints an error and returns False on failure.
    """
    expected_width = None

    for row in board:
        if expected_width is None:
            expected_width = len(row)
        elif len(row) != expected_width:
            print(ERROR_ROW_WIDTH_MISMATCH)
            return False

        for token in row:
            if token not in VALID_TOKENS:
                print(ERROR_UNKNOWN_TOKEN)
                return False

    return True


