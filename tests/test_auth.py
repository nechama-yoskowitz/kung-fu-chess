"""
Focused tests for the authentication layer (Slide 5).

Covers:
- Schema creation
- Register creates user
- Password is never stored as plaintext
- Authenticate succeeds with correct password
- Authenticate fails with wrong password
- Duplicate username rejected
- Whitespace username rejected
- Empty password rejected
- Username trimming
- Default rating = 1200
- UserRepository returns UserRecord
- UserRecord is immutable
- In-memory SQLite works
- SQL injection-like usernames handled safely
"""

import dataclasses

import pytest

from game.server.auth.password_hasher import PasswordHasher
from game.server.auth.user_record import UserRecord
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def repo():
    """In-memory repository, schema initialized."""
    r = UserRepository(":memory:")
    r.initialize_schema()
    return r


@pytest.fixture
def service(repo):
    """UserService backed by in-memory repository."""
    return UserService(repo)


# ─── PasswordHasher ───────────────────────────────────────────────────────────


class TestPasswordHasher:
    def test_hash_returns_string(self):
        h = PasswordHasher.hash("secret")
        assert isinstance(h, str)
        assert len(h) > 0

    def test_hash_contains_separator(self):
        h = PasswordHasher.hash("pass123")
        assert "$" in h

    def test_hash_not_plaintext(self):
        h = PasswordHasher.hash("mypassword")
        assert "mypassword" not in h

    def test_verify_correct_password(self):
        h = PasswordHasher.hash("correct")
        assert PasswordHasher.verify("correct", h) is True

    def test_verify_wrong_password(self):
        h = PasswordHasher.hash("correct")
        assert PasswordHasher.verify("wrong", h) is False

    def test_different_hashes_for_same_password(self):
        """Random salt ensures different hashes each time."""
        h1 = PasswordHasher.hash("same")
        h2 = PasswordHasher.hash("same")
        assert h1 != h2

    def test_verify_malformed_hash_returns_false(self):
        assert PasswordHasher.verify("anything", "not_a_valid_hash") is False
        assert PasswordHasher.verify("anything", "") is False

    def test_verify_invalid_hex_returns_false(self):
        assert PasswordHasher.verify("x", "zzzz$zzzz") is False


# ─── UserRecord ───────────────────────────────────────────────────────────────


class TestUserRecord:
    def test_immutable(self):
        record = UserRecord(id=1, username="alice", password_hash="h", rating=1200)
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.username = "bob"

    def test_fields(self):
        record = UserRecord(id=42, username="bob", password_hash="x$y", rating=1500)
        assert record.id == 42
        assert record.username == "bob"
        assert record.password_hash == "x$y"
        assert record.rating == 1500


# ─── UserRepository ──────────────────────────────────────────────────────────


class TestUserRepositorySchema:
    def test_initialize_schema_creates_table(self, repo):
        # If schema was created, username_exists should work without error
        assert repo.username_exists("nobody") is False

    def test_initialize_schema_idempotent(self, repo):
        # Calling again should not raise
        repo.initialize_schema()
        assert repo.username_exists("nobody") is False

    def test_in_memory_database_works(self):
        r = UserRepository(":memory:")
        r.initialize_schema()
        r.create_user("test", "hash", 1200)
        assert r.username_exists("test") is True


class TestUserRepositoryCRUD:
    def test_create_user_returns_record(self, repo):
        record = repo.create_user("alice", "hash123")
        assert isinstance(record, UserRecord)
        assert record.username == "alice"
        assert record.password_hash == "hash123"
        assert record.rating == 1200
        assert record.id >= 1

    def test_create_user_default_rating(self, repo):
        record = repo.create_user("bob", "h")
        assert record.rating == 1200

    def test_create_user_custom_rating(self, repo):
        record = repo.create_user("charlie", "h", rating=1500)
        assert record.rating == 1500

    def test_username_exists_after_create(self, repo):
        repo.create_user("dave", "h")
        assert repo.username_exists("dave") is True

    def test_username_not_exists(self, repo):
        assert repo.username_exists("ghost") is False

    def test_get_user_by_username(self, repo):
        repo.create_user("eve", "secret_hash")
        record = repo.get_user_by_username("eve")
        assert record is not None
        assert record.username == "eve"
        assert record.password_hash == "secret_hash"

    def test_get_user_not_found(self, repo):
        result = repo.get_user_by_username("nobody")
        assert result is None

    def test_duplicate_username_raises(self, repo):
        repo.create_user("frank", "h1")
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            repo.create_user("frank", "h2")

    def test_sql_injection_username_safe(self, repo):
        """SQL injection-like username is stored literally, not executed."""
        evil = "'; DROP TABLE users; --"
        record = repo.create_user(evil, "hash")
        assert record.username == evil
        # Table still works
        assert repo.username_exists(evil) is True
        repo.create_user("normal", "h")
        assert repo.username_exists("normal") is True


# ─── UserService ──────────────────────────────────────────────────────────────


class TestUserServiceRegister:
    def test_register_success(self, service):
        result = service.register("alice", "password123")
        assert result.success is True
        assert result.user is not None
        assert result.user.username == "alice"
        assert result.error is None

    def test_register_default_rating(self, service):
        result = service.register("bob", "pass")
        assert result.user.rating == 1200

    def test_register_password_not_stored_plaintext(self, service):
        result = service.register("carol", "mysecret")
        assert "mysecret" not in result.user.password_hash

    def test_register_duplicate_username_rejected(self, service):
        service.register("dave", "pass1")
        result = service.register("dave", "pass2")
        assert result.success is False
        assert result.error == "username_taken"

    def test_register_empty_username_rejected(self, service):
        result = service.register("", "pass")
        assert result.success is False
        assert result.error == "empty_username"

    def test_register_whitespace_username_rejected(self, service):
        result = service.register("   ", "pass")
        assert result.success is False
        assert result.error == "empty_username"

    def test_register_empty_password_rejected(self, service):
        result = service.register("eve", "")
        assert result.success is False
        assert result.error == "empty_password"

    def test_register_trims_username(self, service):
        result = service.register("  frank  ", "pass")
        assert result.success is True
        assert result.user.username == "frank"

    def test_register_trimmed_duplicate_detected(self, service):
        service.register("grace", "p1")
        result = service.register("  grace  ", "p2")
        assert result.success is False
        assert result.error == "username_taken"


class TestUserServiceAuthenticate:
    def test_authenticate_success(self, service):
        service.register("heidi", "correct_pass")
        result = service.authenticate("heidi", "correct_pass")
        assert result.success is True
        assert result.user is not None
        assert result.user.username == "heidi"

    def test_authenticate_wrong_password(self, service):
        service.register("ivan", "real_pass")
        result = service.authenticate("ivan", "wrong_pass")
        assert result.success is False
        assert result.error == "invalid_credentials"

    def test_authenticate_nonexistent_user(self, service):
        result = service.authenticate("ghost", "anything")
        assert result.success is False
        assert result.error == "invalid_credentials"

    def test_authenticate_empty_username(self, service):
        result = service.authenticate("", "pass")
        assert result.success is False
        assert result.error == "empty_username"

    def test_authenticate_empty_password(self, service):
        service.register("judy", "real")
        result = service.authenticate("judy", "")
        assert result.success is False
        assert result.error == "empty_password"

    def test_authenticate_trims_username(self, service):
        service.register("kate", "pass")
        result = service.authenticate("  kate  ", "pass")
        assert result.success is True

    def test_authenticate_preserves_rating(self, service):
        service.register("leo", "pass")
        result = service.authenticate("leo", "pass")
        assert result.user.rating == 1200
