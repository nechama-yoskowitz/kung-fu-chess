"""
Authoritative starting board definition.

The template is stored as an immutable token list. Use make_starting_board()
to get a fresh mutable copy suitable for passing to GameEngine.
"""

_STARTING_BOARD_TEMPLATE: tuple[tuple[str, ...], ...] = (
    ("bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"),
    ("bP", "bP", "bP", "bP", "bP", "bP", "bP", "bP"),
    (".", ".", ".", ".", ".", ".", ".", "."),
    (".", ".", ".", ".", ".", ".", ".", "."),
    (".", ".", ".", ".", ".", ".", ".", "."),
    (".", ".", ".", ".", ".", ".", ".", "."),
    ("wP", "wP", "wP", "wP", "wP", "wP", "wP", "wP"),
    ("wR", "wN", "wB", "wQ", "wK", "wB", "wN", "wR"),
)


def make_starting_board() -> list[list[str]]:
    """Return a fresh mutable copy of the standard starting board (legacy token format)."""
    return [list(row) for row in _STARTING_BOARD_TEMPLATE]
