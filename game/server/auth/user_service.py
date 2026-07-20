"""
Authentication business logic: registration and credential verification.

Validates input, delegates hashing to PasswordHasher,
and delegates persistence to UserRepository.
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


class UserService:
    """
    High-level authentication operations.

    Owns validation rules and orchestrates hasher + repository.
    """

    def __init__(self, repository: UserRepository):
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
        except sqlite3.IntegrityError:
            # Race condition: another caller registered between check and insert
            return AuthResult(success=False, error="username_taken")

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
