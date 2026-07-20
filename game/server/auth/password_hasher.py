"""
Password hashing using standard-library cryptography only.

Uses PBKDF2-HMAC-SHA256 with a random per-user salt.
Verification uses hmac.compare_digest for timing-attack safety.
"""

import hashlib
import hmac
import os

# Tunable parameters
_SALT_LENGTH = 16  # bytes
_ITERATIONS = 100_000
_HASH_ALGORITHM = "sha256"
_DK_LENGTH = 32  # derived key length in bytes
_SEPARATOR = "$"


class PasswordHasher:
    """
    Stateless password hashing utility.

    Storage format: base64(salt)$base64(derived_key)
    Both salt and derived key are hex-encoded for safe storage.
    """

    @staticmethod
    def hash(password: str) -> str:
        """
        Hash a plaintext password with a random salt.

        Returns a string suitable for database storage:
            hex_salt$hex_derived_key
        """
        salt = os.urandom(_SALT_LENGTH)
        dk = hashlib.pbkdf2_hmac(
            _HASH_ALGORITHM,
            password.encode("utf-8"),
            salt,
            _ITERATIONS,
            dklen=_DK_LENGTH,
        )
        return f"{salt.hex()}{_SEPARATOR}{dk.hex()}"

    @staticmethod
    def verify(password: str, stored_hash: str) -> bool:
        """
        Verify a plaintext password against a stored hash.

        Uses constant-time comparison to prevent timing attacks.
        Returns True if the password matches, False otherwise.
        """
        parts = stored_hash.split(_SEPARATOR)
        if len(parts) != 2:
            return False

        salt_hex, dk_hex = parts
        try:
            salt = bytes.fromhex(salt_hex)
            expected_dk = bytes.fromhex(dk_hex)
        except ValueError:
            return False

        actual_dk = hashlib.pbkdf2_hmac(
            _HASH_ALGORITHM,
            password.encode("utf-8"),
            salt,
            _ITERATIONS,
            dklen=_DK_LENGTH,
        )

        return hmac.compare_digest(actual_dk, expected_dk)
