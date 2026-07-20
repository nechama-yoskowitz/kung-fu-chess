"""
Immutable data object representing a row in the users table.

Contains no database logic, no authentication logic, no hashing logic.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class UserRecord:
    """Immutable representation of a persisted user."""

    id: int
    username: str
    password_hash: str
    rating: int
