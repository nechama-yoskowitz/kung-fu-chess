import sys


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
