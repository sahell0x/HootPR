import pytest
from app.settings import Settings


@pytest.fixture
def settings() -> Settings:
    """Hermetic settings for eval tests: no .env, local sandbox."""
    return Settings(_env_file=None, sandbox_backend="local")
