"""Tests for SMA background poller."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from sma_client import SmaApiError
from sma_poller import SmaPoller


class TestSmaPoller:
    @pytest.mark.asyncio
    async def test_poll_once_stores_reading(self, test_engine):
        mock_client = MagicMock()
        mock_client.read_measurement = AsyncMock(
            return_value={
                "1-0:16.7.0": {"value": 1500},
                "1-0:1.8.0": {"value": 10000000},
                "1-0:2.8.0": {"value": 500000},
            }
        )
        mock_client.close = AsyncMock()

        poller = SmaPoller(mock_client, test_engine, poll_interval=30)
        await poller._poll_once()
        await poller.stop()

        async with test_engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM sma_readings"))
            assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_poll_once_logs_connection_error(self, test_engine):
        mock_client = MagicMock()
        mock_client.read_measurement = AsyncMock(side_effect=SmaApiError("Connection refused"))
        mock_client.close = AsyncMock()

        poller = SmaPoller(mock_client, test_engine, poll_interval=30)
        await poller._poll_once()
        await poller.stop()

        async with test_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT success, error_message FROM connection_log ORDER BY id DESC LIMIT 1")
            )
            row = result.mappings().fetchone()
            assert row is not None
            assert row["success"] == 0
            assert "Connection refused" in row["error_message"]

    @pytest.mark.asyncio
    async def test_poll_once_no_readable_data(self, test_engine):
        mock_client = MagicMock()
        mock_client.read_measurement = AsyncMock(
            return_value={
                "api_version": "1.0",
            }
        )
        mock_client.close = AsyncMock()

        poller = SmaPoller(mock_client, test_engine, poll_interval=30)
        await poller._poll_once()
        await poller.stop()

        async with test_engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM sma_readings"))
            assert result.scalar() == 0

            result = await conn.execute(
                text("SELECT success FROM connection_log ORDER BY id DESC LIMIT 1")
            )
            row = result.mappings().fetchone()
            assert row is not None
            assert row["success"] == 0

    @pytest.mark.asyncio
    async def test_refresh_daily_summary(self, test_engine):
        mock_client = MagicMock()
        mock_client.read_measurement = AsyncMock(
            return_value={
                "1-0:16.7.0": {"value": 1500},
                "1-0:1.8.0": {"value": 10000000},
                "1-0:2.8.0": {"value": 500000},
            }
        )
        mock_client.close = AsyncMock()

        poller = SmaPoller(mock_client, test_engine, poll_interval=30)
        await poller._poll_once()
        await poller.stop()

        async with test_engine.connect() as conn:
            result = await conn.execute(text("SELECT * FROM daily_energy_summary LIMIT 1"))
            row = result.mappings().fetchone()
            assert row is not None
            assert row["reading_count"] == 1
            assert row["energy_import_kwh"] == 0.0  # only one reading, delta is 0

    @pytest.mark.asyncio
    async def test_start_stop(self, test_engine):
        mock_client = MagicMock()
        mock_client.read_measurement = AsyncMock(
            return_value={
                "1-0:16.7.0": {"value": 1500},
                "1-0:1.8.0": {"value": 10000000},
            }
        )
        mock_client.close = AsyncMock()

        poller = SmaPoller(mock_client, test_engine, poll_interval=1)
        await poller.start()
        await asyncio.sleep(0.1)
        await poller.stop()

        mock_client.close.assert_awaited_once()
