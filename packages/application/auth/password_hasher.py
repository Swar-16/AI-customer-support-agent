# AI-customer-support-agent\packages\application\auth\password_hasher.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from argon2 import PasswordHasher
from argon2.exceptions import HashingError, InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

from packages.application.auth.exceptions import PasswordHashingError

class PasswordHasherContract(Protocol):
    def hash_password(self, password: str) -> str:
        """Return a secure encoded hash for a plaintext password."""
        ...

    def verify_password(self, *, password: str, password_hash: str) -> bool:
        """Return whether the plaintext password matches the encoded hash."""
        ...

    def needs_rehash(self, password_hash: str) -> bool:
        """Return whether the hash should be replaced with current settings."""
        ...

@dataclass(frozen=True, slots=True)
class Argon2PasswordHasherConfig:
    """
    Argon2id configuration.

    memory_cost is measured in KiB.
    """
    time_cost: int = 2
    memory_cost: int = 19_456
    parallelism: int = 1
    hash_length: int = 32
    salt_length: int = 16

    def __post_init__(self) -> None:
        if self.time_cost <= 0:
            raise ValueError("time_cost must be greater than zero")

        if self.memory_cost <= 0:
            raise ValueError("memory_cost must be greater than zero")

        if self.parallelism <= 0:
            raise ValueError("parallelism must be greater than zero")

        if self.hash_length <= 0:
            raise ValueError("hash_length must be greater than zero")

        if self.salt_length <= 0:
            raise ValueError("salt_length must be greater than zero")


class Argon2PasswordHasher:
    """
    Argon2id password-hashing adapter.

    Application services depend on PasswordHasherContract instead of directly depending on argon2-cffi.
    """
    def __init__(self, config: Argon2PasswordHasherConfig | None = None) -> None:
        resolved_config = config or Argon2PasswordHasherConfig()

        self._hasher = PasswordHasher(
            time_cost=resolved_config.time_cost,
            memory_cost=resolved_config.memory_cost,
            parallelism=resolved_config.parallelism,
            hash_len=resolved_config.hash_length,
            salt_len=resolved_config.salt_length,
            type=Type.ID,
        )

    def hash_password(self, password: str) -> str:
        normalized_password = self._validate_password(password)

        try:
            return self._hasher.hash(normalized_password)
        
        except HashingError as exc:
            raise PasswordHashingError("The password could not be securely hashed.") from exc

    def verify_password(self, *, password: str, password_hash: str) -> bool:
        if not isinstance(password, str):
            return False

        if not isinstance(password_hash, str) or not password_hash.strip():
            return False

        try:
            return self._hasher.verify(password_hash, password)
        
        except (VerifyMismatchError, InvalidHashError, VerificationError,):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        if not isinstance(password_hash, str) or not password_hash.strip():
            return True

        try:
            return self._hasher.check_needs_rehash(password_hash)
        
        except InvalidHashError:
            return True

    @staticmethod
    def _validate_password(password: str) -> str:
        if not isinstance(password, str):
            raise TypeError("password must be a string")

        if not password:
            raise ValueError("password cannot be empty")

        # Argon2 implementations commonly reject passwords whose encoded representation is excessively large.
        # Bounding the input also avoids unnecessary resource consumption from hostile requests.
        if len(password.encode("utf-8")) > 1_024:
            raise ValueError("password cannot exceed 1024 UTF-8 encoded bytes")

        return password