"""
Authentication business logic: registration and credential verification.

Validates input, delegates hashing to PasswordHasher,
and delegates persistence to UserRepository.

Works with any repository that implements the UserRepository public API
(currently: UserRepository/SQLite and PostgresUserRepository/PostgreSQL).
"""

from dataclasses import dataclass
import sqlite3

from game.server.auth.password_hasher import PasswordHasher
from game.server.auth.user_record import UserRecord
from game.server.auth.user_repository import UserRepository


@dataclass(frozen=True)
class AuthResult:
    """Outcome of a register or authenticate operation."""

    success: bool
    user: UserRecord | None = None
    error: str | None = None


def _is_unique_violation(exc: Exception) -> bool:
    """
    Return True if the exception represents a unique-constraint violation.

    Handles both SQLite (sqlite3.IntegrityError) and
    PostgreSQL (psycopg.errors.UniqueViolation, which is a subclass of
    psycopg.IntegrityError). Uses try/except for lazy import so the
    psycopg package is not required for tests that only use SQLite.
    """
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    try:
        import psycopg  # type: ignore[import-not-found]
        if isinstance(exc, psycopg.IntegrityError):
            return True
    except ImportError:
        pass
    return False


class UserService:
    """
    High-level authentication operations.

    Owns validation rules and orchestrates hasher + repository.
    Accepts any repository that exposes the UserRepository interface.
    """

    def __init__(self, repository):
        self._repo = repository
        self._hasher = PasswordHasher()

    def register(self, username: str, password: str) -> AuthResult:
        """
        Register a new user.

        Validates input, hashes the password, and persists the user.
        Returns AuthResult with success=True and the UserRecord on success,
        or success=False with an error reason on failure.
        """
        # Validate username
        validation_error = self._validate_username(username)
        if validation_error:
            return AuthResult(success=False, error=validation_error)

        # Validate password
        validation_error = self._validate_password(password)
        if validation_error:
            return AuthResult(success=False, error=validation_error)

        trimmed = username.strip()

        # Check duplicate
        if self._repo.username_exists(trimmed):
            return AuthResult(success=False, error="username_taken")

        # Hash and persist
        password_hash = self._hasher.hash(password)
        try:
            user = self._repo.create_user(trimmed, password_hash)
        except Exception as exc:
            if _is_unique_violation(exc):
                # Race condition: another caller registered between check and insert
                return AuthResult(success=False, error="username_taken")
            raise

        return AuthResult(success=True, user=user)

    def authenticate(self, username: str, password: str) -> AuthResult:
        """
        Verify credentials for an existing user.

        Returns AuthResult with success=True and the UserRecord on success,
        or success=False with an error reason on failure.
        """
        # Validate inputs
        validation_error = self._validate_username(username)
        if validation_error:
            return AuthResult(success=False, error=validation_error)

        if not password:
            return AuthResult(success=False, error="empty_password")

        trimmed = username.strip()
        user = self._repo.get_user_by_username(trimmed)

        if user is None:
            return AuthResult(success=False, error="invalid_credentials")

        if not self._hasher.verify(password, user.password_hash):
            return AuthResult(success=False, error="invalid_credentials")

        return AuthResult(success=True, user=user)

    @staticmethod
    def _validate_username(username: str) -> str | None:
        """Return error string if username is invalid, None if OK."""
        if not username:
            return "empty_username"
        if not username.strip():
            return "empty_username"
        return None

    @staticmethod
    def _validate_password(password: str) -> str | None:
        """Return error string if password is invalid, None if OK."""
        if not password:
            return "empty_password"
        return None
