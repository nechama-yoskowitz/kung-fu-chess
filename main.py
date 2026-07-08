import sys

CELL_SIZE = 100

def parse_input():
    lines = sys.stdin.read().splitlines()

    board_lines = []
    commands = []

    in_board = False
    in_commands = False

    for line in lines:
        line = line.strip()

        if line == "Board:":
            in_board = True
            in_commands = False
            continue

        if line == "Commands:":
            in_board = False
            in_commands = True
            continue

        if in_board:
            board_lines.append(line)
        elif in_commands:
            if line != "":
                commands.append(line)

    board = []
    for line in board_lines:
        board.append(line.split())

    return board, commands


def validate_board(board):
    valid_pieces = {
        ".",
        "wK", "wQ", "wR", "wB", "wN", "wP",
        "bK", "bQ", "bR", "bB", "bN", "bP"
    }

    expected_width = None

    for row in board:
        if expected_width is None:
            expected_width = len(row)
        elif len(row) != expected_width:
            print("ERROR ROW_WIDTH_MISMATCH")
            return False

        for token in row:
            if token not in valid_pieces:
                print("ERROR UNKNOWN_TOKEN")
                return False

    return True


def print_board(board):
    for row in board:
        print(" ".join(row))


def is_inside_board(board, row, col):
    return 0 <= row < len(board) and 0 <= col < len(board[0])


def same_color(piece1, piece2):
    return piece1 != "." and piece2 != "." and piece1[0] == piece2[0]
    
def is_legal_move(piece, from_row, from_col, to_row, to_col):
    row_diff = abs(to_row - from_row)
    col_diff = abs(to_col - from_col)

    piece_type = piece[1]   # K, R, B, Q, N

    if piece_type == "K":
        return row_diff <= 1 and col_diff <= 1

    elif piece_type == "R":
        return from_row == to_row or from_col == to_col

    elif piece_type == "B":
        return row_diff == col_diff

    elif piece_type == "Q":
        return (
            from_row == to_row or
            from_col == to_col or
            row_diff == col_diff
        )

    elif piece_type == "N":
        return (
            (row_diff == 2 and col_diff == 1) or
            (row_diff == 1 and col_diff == 2)
        )

    return False   

def is_legal_pawn_move(board, piece, from_row, from_col, to_row, to_col):
    row_diff = to_row - from_row
    col_diff = to_col - from_col

    target = board[to_row][to_col]
    color = piece[0]

    if color == "w":
        direction = -1
    else:
        direction = 1

    if row_diff == direction and col_diff == 0:
        return target == "."

    if row_diff == direction and abs(col_diff) == 1:
        return target != "." and target[0] != color

    return False    

def is_path_clear(board, from_row, from_col, to_row, to_col):
    row_step = 0
    col_step = 0

    if to_row > from_row:
        row_step = 1
    elif to_row < from_row:
        row_step = -1

    if to_col > from_col:
        col_step = 1
    elif to_col < from_col:
        col_step = -1

    current_row = from_row + row_step
    current_col = from_col + col_step

    while (current_row, current_col) != (to_row, to_col):

        if board[current_row][current_col] != ".":
            return False

        current_row += row_step
        current_col += col_step

    return True

def handle_click(board, selected, x, y):
    row = y // CELL_SIZE
    col = x // CELL_SIZE

    if not is_inside_board(board, row, col):
        return selected

    clicked_cell = board[row][col]

    if selected is None:
        if clicked_cell != ".":
            return (row, col)
        return None

    selected_row, selected_col = selected
    selected_piece = board[selected_row][selected_col]

    if clicked_cell != "." and same_color(selected_piece, clicked_cell):
        return (row, col)

    if selected_piece[1] == "P":
        if not is_legal_pawn_move(board, selected_piece, selected_row, selected_col, row, col):
            return None

        board[row][col] = selected_piece
        board[selected_row][selected_col] = "."
        return None

    if not is_legal_move(selected_piece, selected_row, selected_col, row, col):
        return None

    if selected_piece[1] != "N":
        if not is_path_clear(board, selected_row, selected_col, row, col):
            return None

    board[row][col] = selected_piece
    board[selected_row][selected_col] = "."

    return None

def handle_wait(clock, ms):
    return clock + ms


def process_commands(board, commands):
    selected = None
    clock = 0

    for command in commands:
        parts = command.split()

        if command == "print board":
            print_board(board)

        elif parts[0] == "click":
            x = int(parts[1])
            y = int(parts[2])
            selected = handle_click(board, selected, x, y)

        elif parts[0] == "wait":
            ms = int(parts[1])
            clock = handle_wait(clock, ms)


def main():
    
    board, commands = parse_input()

    if not validate_board(board):
        return

    process_commands(board, commands)


if __name__ == "__main__":
    main()