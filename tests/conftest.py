"""Test configuration and fixtures."""

import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from db_init import init_database

# Create temp directories before any app imports
TEST_DATA_DIR = tempfile.mkdtemp(prefix="sma_energy_tracker_data_")
TEST_STATIC_DIR = tempfile.mkdtemp(prefix="sma_energy_tracker_static_")

# Create a minimal index.html so StaticFiles doesn't complain
Path(TEST_STATIC_DIR, "index.html").write_text("<html><body>Test</body></html>")

# Patch environment before importing app modules
os.environ["DATA_DIR"] = TEST_DATA_DIR
os.environ["STATIC_DIR"] = TEST_STATIC_DIR
# Ensure SMA poller does not start during tests
os.environ.pop("SMA_HOST", None)
os.environ.pop("SMA_TOKEN", None)

import app as app_module  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_resources():
    """Remove temporary resources after the test session."""
    yield
    import shutil

    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
    shutil.rmtree(TEST_STATIC_DIR, ignore_errors=True)


@pytest_asyncio.fixture(scope="function")
async def test_engine(tmp_path: Path):
    """Create a fresh temporary database engine for direct testing."""
    db_path = tmp_path / "test.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"

    engine = create_async_engine(database_url, pool_pre_ping=True)
    await init_database(engine)

    yield engine

    await engine.dispose()


@pytest.fixture(scope="function")
def client(tmp_path: Path):
    """Create a TestClient with a fresh test database."""
    db_path = tmp_path / "test.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"

    original_database_url = app_module.DATABASE_URL
    app_module.DATABASE_URL = database_url

    with TestClient(app_module.app) as c:
        yield c

    app_module.DATABASE_URL = original_database_url
