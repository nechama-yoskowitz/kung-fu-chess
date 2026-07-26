"""
Board conversion adapter — bridges domain Piece|None boards and legacy string boards.

This module provides the ONLY conversion point between the internal domain
representation (Piece objects and None) and the legacy string representation
("wR", "bK", ".") used by graphics, network protocol, and client state.

Usage:
- Core domain (engine, rules, realtime) works with Piece|None boards
- At boundary points, convert with to_legacy_board() before passing to
  graphics, network serialization, or client code
- When receiving boards from external sources (network, legacy tests),
  convert with to_domain_board()

Delegates all token logic to game.io.piece_token_codec.
"""

from game.io.piece_token_codec import format_board, format_piece, parse_board, parse_token
from game.model.piece import Piece


def to_legacy_board(board: list[list]) -> list[list[str]]:
    """
    Convert a domain board (Piece|None) to a legacy string board.

    If the board already contains strings (during migration), returns as-is.
    """
    if not board:
        return board
    # Check if already legacy format
    first_row = board[0]
    if first_row and isinstance(first_row[0], str):
        return board  # Already legacy — no conversion needed
    return format_board(board)


def to_domain_board(board: list[list]) -> list[list]:
    """
    Convert a legacy string board to a domain board (Piece|None) IN-PLACE.

    If the board already contains Piece objects (during migration), returns as-is.
    Mutates the original list so that existing references see domain objects.
    """
    if not board:
        return board
    # Check if already domain format
    first_row = board[0]
    if first_row and (first_row[0] is None or isinstance(first_row[0], Piece)):
        return board  # Already domain — no conversion needed
    # Convert in-place so callers holding a reference to board see the change
    for r, row in enumerate(board):
        for c, cell in enumerate(row):
            row[c] = parse_token(cell)
    return board


def to_legacy_piece(piece) -> str:
    """
    Convert a single domain piece (Piece|None) to legacy token.

    If already a string, returns as-is.
    """
    if isinstance(piece, str):
        return piece
    return format_piece(piece)


def to_domain_piece(piece) -> Piece | None:
    """
    Convert a single legacy token to domain piece.

    If already a Piece or None, returns as-is.
    """
    if piece is None or isinstance(piece, Piece):
        return piece
    return parse_token(piece)
