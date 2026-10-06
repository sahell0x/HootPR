"""Fernet encryption for tokens at rest (`*_enc` columns)."""

from cryptography.fernet import Fernet, InvalidToken


class DecryptionError(Exception):
    """Ciphertext could not be decrypted with the configured key."""


class Crypto:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except (InvalidToken, ValueError) as exc:
            raise DecryptionError("cannot decrypt value") from exc
