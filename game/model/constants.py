from game.model.piece import PieceType

CELL_SIZE = 100

# --- Legacy constants kept for IO/boundary layers ---
EMPTY_CELL = "."

WHITE = "w"
BLACK = "b"

PIECE_KING   = "K"
PIECE_QUEEN  = "Q"
PIECE_ROOK   = "R"
PIECE_BISHOP = "B"
PIECE_KNIGHT = "N"
PIECE_PAWN   = "P"

VALID_TOKENS = {
    EMPTY_CELL,
    "wK", "wQ", "wR", "wB", "wN", "wP",
    "bK", "bQ", "bR", "bB", "bN", "bP",
}

ERROR_ROW_WIDTH_MISMATCH = "ERROR ROW_WIDTH_MISMATCH"
ERROR_UNKNOWN_TOKEN      = "ERROR UNKNOWN_TOKEN"

# --- Domain constants keyed by PieceType ---

SLIDING_PIECES = {PieceType.QUEEN, PieceType.ROOK, PieceType.BISHOP}

MOVEMENT_RULES = {
    PieceType.KING:   lambda dr, dc: dr <= 1 and dc <= 1,
    PieceType.ROOK:   lambda dr, dc: dr == 0 or dc == 0,
    PieceType.BISHOP: lambda dr, dc: dr == dc,
    PieceType.QUEEN:  lambda dr, dc: dr == 0 or dc == 0 or dr == dc,
    PieceType.KNIGHT: lambda dr, dc: (dr == 2 and dc == 1) or (dr == 1 and dc == 2),
}

# How long (in ms) it takes for a piece to travel from source to destination.
MOVE_DURATION_MS = 1000

# How long (in ms) a jump/airborne state lasts.
JUMP_DURATION_MS = 3500

# How long (in ms) a piece rests after arriving at its destination.
COOLDOWN_DURATION_MS = 2000

# Material value of each piece type for scoring.
PIECE_VALUES = {
    PieceType.PAWN:   1,
    PieceType.KNIGHT: 3,
    PieceType.BISHOP: 3,
    PieceType.ROOK:   5,
    PieceType.QUEEN:  9,
    PieceType.KING:   0,
}

# Default Elo rating for new players.
DEFAULT_RATING = 1200
