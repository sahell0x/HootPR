import pytest
from cryptography.fernet import Fernet

from app.crypto import Crypto, DecryptionError


def test_round_trip() -> None:
    c = Crypto(Fernet.generate_key())
    token = c.encrypt("glpat-secret")
    assert token != "glpat-secret"
    assert c.decrypt(token) == "glpat-secret"


def test_wrong_key_raises() -> None:
    token = Crypto(Fernet.generate_key()).encrypt("x")
    with pytest.raises(DecryptionError):
        Crypto(Fernet.generate_key()).decrypt(token)


def test_garbage_raises() -> None:
    with pytest.raises(DecryptionError):
        Crypto(Fernet.generate_key()).decrypt("not-a-token")
