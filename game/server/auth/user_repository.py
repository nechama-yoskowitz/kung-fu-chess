"""
SQLite persistence layer for user accounts.

Responsible only for CRUD operations on the users table.
No business logic, no hashing, no validation beyond what SQL enforces.
"""

import sqlite3

from game.model.constants import DEFAULT_RATING
from game.server.auth.user_record import UserRecord

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    rating INTEGER NOT NULL DEFAULT 1200
);
"""


class UserRepository:
    """
    SQLite-backed user persistence.

    Supports both file-based and in-memory databases.
    Each public method opens and closes its own connection to avoid
    holding long-lived connections (safe for single-writer SQLite).
    """

    def __init__(self, db_path: str = "kungfu_chess.db"):
        """
        Parameters
        ----------
        db_path : str
            Path to the SQLite database file.
            Use ":memory:" for in-memory databases (useful for tests).
        """
        self._db_path = db_path
        # For in-memory databases, keep a single connection alive
        # (closing it would destroy the data).
        # Set check_same_thread=False to allow use from ThreadPoolExecutor.
        if db_path == ":memory:":
            self._shared_conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._shared_conn = None

    def _get_connection(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        return sqlite3.connect(self._db_path)

    def _close_connection(self, conn: sqlite3.Connection) -> None:
        if conn is not self._shared_conn:
            conn.close()

    def initialize_schema(self) -> None:
        """Create the users table if it does not exist."""
        conn = self._get_connection()
        try:
            conn.execute(_SCHEMA_SQL)
            conn.commit()
        finally:
            self._close_connection(conn)

    def username_exists(self, username: str) -> bool:
        """Check if a username is already registered."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT 1 FROM users WHERE username = ? LIMIT 1",
                (username,),
            )
            return cursor.fetchone() is not None
        finally:
            self._close_connection(conn)

    def create_user(
        self,
        username: str,
        password_hash: str,
        rating: int = DEFAULT_RATING,
    ) -> UserRecord:
        """
        Insert a new user and return the created record.

        Raises sqlite3.IntegrityError if the username already exists.
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, rating) VALUES (?, ?, ?)",
                (username, password_hash, rating),
            )
            conn.commit()
            return UserRecord(
                id=cursor.lastrowid,
                username=username,
                password_hash=password_hash,
                rating=rating,
            )
        finally:
            self._close_connection(conn)

    def get_user_by_username(self, username: str) -> UserRecord | None:
        """
        Look up a user by username.

        Returns a UserRecord if found, None otherwise.
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT id, username, password_hash, rating FROM users WHERE username = ?",
                (username,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return UserRecord(
                id=row[0],
                username=row[1],
                password_hash=row[2],
                rating=row[3],
            )
        finally:
            self._close_connection(conn)

    def update_rating(self, username: str, new_rating: int) -> None:
        """
        Update a user's rating.

        Raises ValueError if the user does not exist.
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "UPDATE users SET rating = ? WHERE username = ?",
                (new_rating, username),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User not found: {username}")
        finally:
            self._close_connection(conn)

    def update_ratings(
        self,
        winner_username: str,
        winner_rating: int,
        loser_username: str,
        loser_rating: int,
    ) -> None:
        """
        Atomically update both players' ratings in a single transaction.

        If either user does not exist, both updates are rolled back.
        Raises ValueError if either user is not found.
        """
        conn = self._get_connection()
        try:
            cursor1 = conn.execute(
                "UPDATE users SET rating = ? WHERE username = ?",
                (winner_rating, winner_username),
            )
            cursor2 = conn.execute(
                "UPDATE users SET rating = ? WHERE username = ?",
                (loser_rating, loser_username),
            )
            if cursor1.rowcount == 0 or cursor2.rowcount == 0:
                conn.rollback()
                missing = winner_username if cursor1.rowcount == 0 else loser_username
                raise ValueError(f"User not found: {missing}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._close_connection(conn)

    def close(self) -> None:
        """Close the shared connection (for in-memory databases)."""
        if self._shared_conn is not None:
            self._shared_conn.close()
            self._shared_conn = None
