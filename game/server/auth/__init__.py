"""
Authentication layer for Kung-Fu Chess server.

Provides user registration, password hashing, and credential verification
backed by SQLite persistence.
"""

from game.server.auth.user_record import UserRecord
from game.server.auth.password_hasher import PasswordHasher
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService

__all__ = ["UserRecord", "PasswordHasher", "UserRepository", "UserService"]
