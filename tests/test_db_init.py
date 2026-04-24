"""Tests for database initialization."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from db_init import SCHEMA_VERSION, init_database


class TestInitDatabase:
    @pytest.mark.asyncio
    async def test_creates_schema_version_table(self, test_engine):
        async with test_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
            )
            assert result.scalar() is not None

    @pytest.mark.asyncio
    async def test_creates_sma_readings_table(self, test_engine):
        async with test_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='sma_readings'")
            )
            assert result.scalar() is not None

    @pytest.mark.asyncio
    async def test_creates_daily_summary_table(self, test_engine):
        async with test_engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_energy_summary'"
                )
            )
            assert result.scalar() is not None

    @pytest.mark.asyncio
    async def test_creates_hourly_pattern_table(self, test_engine):
        async with test_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='hourly_pattern'")
            )
            assert result.scalar() is not None

    @pytest.mark.asyncio
    async def test_creates_connection_log_table(self, test_engine):
        async with test_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='connection_log'")
            )
            assert result.scalar() is not None

    @pytest.mark.asyncio
    async def test_sets_schema_version(self, test_engine):
        async with test_engine.connect() as conn:
            result = await conn.execute(text("SELECT MAX(version) FROM schema_version"))
            version = result.scalar()
            assert version == SCHEMA_VERSION

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_path):
        db_file = tmp_path / "test.db"
        database_url = f"sqlite+aiosqlite:///{db_file}"
        engine = create_async_engine(database_url, pool_pre_ping=True)

        await init_database(engine)
        await init_database(engine)
        await init_database(engine)

        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT MAX(version) FROM schema_version"))
            version = result.scalar()
            assert version == SCHEMA_VERSION

        await engine.dispose()
