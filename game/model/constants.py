CELL_SIZE = 100

EMPTY_CELL = "."

WHITE = "w"
BLACK = "b"

PIECE_KING   = "K"
PIECE_QUEEN  = "Q"
PIECE_ROOK   = "R"
PIECE_BISHOP = "B"
PIECE_KNIGHT = "N"
PIECE_PAWN   = "P"

SLIDING_PIECES = {PIECE_QUEEN, PIECE_ROOK, PIECE_BISHOP}

# Maps each piece type to its movement rule.
# The rule is a callable (row_diff, col_diff) -> bool,
# where both diffs are absolute values.
# To support custom pieces in the future, add an entry here.
MOVEMENT_RULES = {
    PIECE_KING:   lambda dr, dc: dr <= 1 and dc <= 1,
    PIECE_ROOK:   lambda dr, dc: dr == 0 or dc == 0,
    PIECE_BISHOP: lambda dr, dc: dr == dc,
    PIECE_QUEEN:  lambda dr, dc: dr == 0 or dc == 0 or dr == dc,
    PIECE_KNIGHT: lambda dr, dc: (dr == 2 and dc == 1) or (dr == 1 and dc == 2),
}

VALID_TOKENS = {
    EMPTY_CELL,
    "wK", "wQ", "wR", "wB", "wN", "wP",
    "bK", "bQ", "bR", "bB", "bN", "bP",
}

ERROR_ROW_WIDTH_MISMATCH = "ERROR ROW_WIDTH_MISMATCH"
ERROR_UNKNOWN_TOKEN      = "ERROR UNKNOWN_TOKEN"

# How long (in ms) it takes for a piece to travel from source to destination.
MOVE_DURATION_MS = 1000

# How long (in ms) a jump/airborne state lasts.
JUMP_DURATION_MS = 3500

# How long (in ms) a piece rests after arriving at its destination.
COOLDOWN_DURATION_MS = 2000

# Material value of each piece type for scoring.
PIECE_VALUES = {
    PIECE_PAWN:   1,
    PIECE_KNIGHT: 3,
    PIECE_BISHOP: 3,
    PIECE_ROOK:   5,
    PIECE_QUEEN:  9,
    PIECE_KING:   0,
}
