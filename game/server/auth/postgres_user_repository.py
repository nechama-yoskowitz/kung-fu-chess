"""
PostgreSQL persistence layer for user accounts.

Implements the same public interface as UserRepository (SQLite) so
UserService and RatingService work unchanged with both backends.

Requires psycopg (psycopg3) — install with:  pip install "psycopg[binary]"

Connection is managed via a DSN string:
    postgresql://user:password@host:port/dbname

Schema is created by initialize_schema(), which is idempotent and safe
to call on every startup.
"""

import logging

import psycopg
from psycopg.rows import tuple_row

from game.model.constants import DEFAULT_RATING
from game.server.auth.user_record import UserRecord

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    TEXT    NOT NULL UNIQUE,
    password_hash TEXT  NOT NULL,
    rating      INTEGER NOT NULL DEFAULT 1200
);
"""


class PostgresUserRepository:
    """
    PostgreSQL-backed user persistence.

    Exposes the exact same public API as UserRepository so
    UserService and RatingService require no changes.

    Each method opens a short-lived connection from the DSN.
    This is intentionally simple for Stage 1; a connection pool
    (e.g. psycopg_pool) can be added in a later stage.
    """

    def __init__(self, dsn: str):
        """
        Parameters
        ----------
        dsn : str
            PostgreSQL connection string.
            Example: "postgresql://kfc:kfc_secret@localhost:5432/kungfu_chess"
        """
        self._dsn = dsn

    # ─── Schema ──────────────────────────────────────────────────────────────

    def initialize_schema(self) -> None:
        """Create the users table if it does not exist (idempotent)."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(_SCHEMA_SQL)
            conn.commit()
        logger.info("PostgreSQL schema initialized (users table ready)")

    # ─── Read ─────────────────────────────────────────────────────────────────

    def username_exists(self, username: str) -> bool:
        """Return True if the username is already registered."""
        with psycopg.connect(self._dsn, row_factory=tuple_row) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM users WHERE username = %s LIMIT 1",
                (username,),
            )
            return cursor.fetchone() is not None

    def get_user_by_username(self, username: str) -> UserRecord | None:
        """Return a UserRecord for the given username, or None."""
        with psycopg.connect(self._dsn, row_factory=tuple_row) as conn:
            cursor = conn.execute(
                "SELECT id, username, password_hash, rating FROM users WHERE username = %s",
                (username,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return UserRecord(id=row[0], username=row[1], password_hash=row[2], rating=row[3])

    # ─── Write ────────────────────────────────────────────────────────────────

    def create_user(
        self,
        username: str,
        password_hash: str,
        rating: int = DEFAULT_RATING,
    ) -> UserRecord:
        """
        Insert a new user and return the created record.

        Raises psycopg.errors.UniqueViolation (a subclass of
        psycopg.IntegrityError) if the username already exists —
        same semantics as sqlite3.IntegrityError from UserRepository.
        """
        with psycopg.connect(self._dsn, row_factory=tuple_row) as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, rating) "
                "VALUES (%s, %s, %s) RETURNING id",
                (username, password_hash, rating),
            )
            row = cursor.fetchone()
            conn.commit()
            return UserRecord(
                id=row[0],
                username=username,
                password_hash=password_hash,
                rating=rating,
            )

    def update_rating(self, username: str, new_rating: int) -> None:
        """
        Update a single user's rating.

        Raises ValueError if the user does not exist.
        """
        with psycopg.connect(self._dsn) as conn:
            cursor = conn.execute(
                "UPDATE users SET rating = %s WHERE username = %s",
                (new_rating, username),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"User not found: {username}")

    def update_ratings(
        self,
        winner_username: str,
        winner_rating: int,
        loser_username: str,
        loser_rating: int,
    ) -> None:
        """
        Atomically update both players' ratings in a single transaction.

        Raises ValueError if either user does not exist; both updates
        are rolled back on any error.
        """
        with psycopg.connect(self._dsn) as conn:
            try:
                c1 = conn.execute(
                    "UPDATE users SET rating = %s WHERE username = %s",
                    (winner_rating, winner_username),
                )
                c2 = conn.execute(
                    "UPDATE users SET rating = %s WHERE username = %s",
                    (loser_rating, loser_username),
                )
                if c1.rowcount == 0 or c2.rowcount == 0:
                    conn.rollback()
                    missing = winner_username if c1.rowcount == 0 else loser_username
                    raise ValueError(f"User not found: {missing}")
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def close(self) -> None:
        """No-op for interface compatibility with UserRepository."""
        pass
