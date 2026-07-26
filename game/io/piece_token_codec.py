"""
Boundary mapper between external text tokens and internal domain Piece types.

This is the ONLY module that knows the legacy text format:
    "wR" = White Rook
    "bK" = Black King
    "."  = Empty cell (None internally)

All other modules work with Piece objects and None.
"""

from game.model.piece import Piece, PieceColor, PieceType


# ─── External token → Internal Piece ─────────────────────────────────────────

_COLOR_MAP = {
    "w": PieceColor.WHITE,
    "b": PieceColor.BLACK,
}

_TYPE_MAP = {
    "K": PieceType.KING,
    "Q": PieceType.QUEEN,
    "R": PieceType.ROOK,
    "B": PieceType.BISHOP,
    "N": PieceType.KNIGHT,
    "P": PieceType.PAWN,
}

EMPTY_TOKEN = "."

# All valid external tokens
VALID_TOKENS = {EMPTY_TOKEN} | {
    f"{c}{t}" for c in _COLOR_MAP for t in _TYPE_MAP
}


def parse_token(token: str) -> Piece | None:
    """
    Convert an external text token to the internal domain representation.

    Returns None for the empty-cell token ".".
    Raises ValueError for unknown tokens.
    """
    if token == EMPTY_TOKEN:
        return None
    if len(token) != 2:
        raise ValueError(f"Unknown token: {token}")
    color = _COLOR_MAP.get(token[0])
    piece_type = _TYPE_MAP.get(token[1])
    if color is None or piece_type is None:
        raise ValueError(f"Unknown token: {token}")
    return Piece(color, piece_type)


def is_valid_token(token: str) -> bool:
    """Check if a token is a recognized external piece token."""
    return token in VALID_TOKENS


# ─── Internal Piece → External token ─────────────────────────────────────────

_COLOR_TO_CHAR = {
    PieceColor.WHITE: "w",
    PieceColor.BLACK: "b",
}

_TYPE_TO_CHAR = {
    PieceType.KING: "K",
    PieceType.QUEEN: "Q",
    PieceType.ROOK: "R",
    PieceType.BISHOP: "B",
    PieceType.KNIGHT: "N",
    PieceType.PAWN: "P",
}


def format_piece(piece: Piece | None) -> str:
    """
    Convert an internal domain piece (or None) to the external text token.

    None → "."
    Piece(WHITE, ROOK) → "wR"
    """
    if piece is None:
        return EMPTY_TOKEN
    return _COLOR_TO_CHAR[piece.color] + _TYPE_TO_CHAR[piece.type]


def parse_board(token_rows: list[list[str]]) -> list[list[Piece | None]]:
    """Convert a 2D list of external tokens to internal board representation."""
    return [[parse_token(token) for token in row] for row in token_rows]


def format_board(board: list[list[Piece | None]]) -> list[list[str]]:
    """Convert an internal board to a 2D list of external tokens."""
    return [[format_piece(cell) for cell in row] for row in board]
