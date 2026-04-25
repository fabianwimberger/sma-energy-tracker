#!/usr/bin/env python3
"""Background poller for the Smart Meter Adapter."""

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sma_client import SmaApiClient, SmaApiError, extract_reading

logger = logging.getLogger(__name__)
HOURLY_PATTERN_REFRESH_INTERVAL = timedelta(hours=1)


class SmaPoller:
    """Polls the SMA device and stores readings in the database."""

    def __init__(
        self,
        client: SmaApiClient,
        engine: AsyncEngine,
        poll_interval: int = 30,
    ):
        self.client = client
        self.engine = engine
        self.poll_interval = poll_interval
        self._task: asyncio.Task | None = None
        self._last_pattern_refresh: datetime | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background polling task."""
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("SMA poller started (interval=%ds)", self.poll_interval)

    async def stop(self) -> None:
        """Stop the background polling task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.client.close()
        logger.info("SMA poller stopped")

    async def _run_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unexpected error in SMA poller loop")

            # Sleep in small chunks so shutdown is responsive
            for _ in range(self.poll_interval):
                if not self._running:
                    break
                await asyncio.sleep(1)

    async def _poll_once(self) -> None:
        """Perform a single poll cycle."""
        try:
            data = await self.client.read_measurement()
            reading = extract_reading(data)

            if reading is None:
                logger.warning("SMA response contained no readable data")
                await self._log_connection(False, "No readable data in response")
                return

            await self._store_reading(reading)
            await self._log_connection(True)

            # Refresh hourly pattern if needed
            now = datetime.now()
            if (
                self._last_pattern_refresh is None
                or now - self._last_pattern_refresh > HOURLY_PATTERN_REFRESH_INTERVAL
            ):
                await self._refresh_hourly_pattern()
                self._last_pattern_refresh = now

        except SmaApiError as e:
            logger.warning("SMA poll failed: %s", e)
            await self._log_connection(False, str(e))

    async def _store_reading(self, reading: dict[str, Any]) -> None:
        """Insert a reading and refresh the affected daily summary."""
        now = datetime.now()

        async with self.engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT OR REPLACE INTO sma_readings
                        (reading_time, power_import_w, power_export_w, power_sum_w,
                         energy_import_total_kwh, energy_export_total_kwh)
                    VALUES
                        (:reading_time, :power_import_w, :power_export_w, :power_sum_w,
                         :energy_import_total_kwh, :energy_export_total_kwh)
                """),
                {
                    "reading_time": now,
                    "power_import_w": reading.get("power_import_w"),
                    "power_export_w": reading.get("power_export_w"),
                    "power_sum_w": reading.get("power_sum_w"),
                    "energy_import_total_kwh": reading.get("energy_import_total_kwh"),
                    "energy_export_total_kwh": reading.get("energy_export_total_kwh"),
                },
            )

        # Refresh daily summary for today
        today = now.date()
        await self._refresh_daily_summary(today)

    async def _refresh_daily_summary(self, date_obj) -> None:
        """Recalculate daily summary for a given date using counter deltas."""
        async with self.engine.begin() as conn:
            # Get first and last total counter values for the day
            counter_result = await conn.execute(
                text("""
                    SELECT
                        MIN(energy_import_total_kwh) as first_import,
                        MAX(energy_import_total_kwh) as last_import,
                        MIN(energy_export_total_kwh) as first_export,
                        MAX(energy_export_total_kwh) as last_export
                    FROM sma_readings
                    WHERE DATE(reading_time) = :date
                      AND energy_import_total_kwh IS NOT NULL
                """),
                {"date": date_obj.isoformat()},
            )
            counter_row = counter_result.mappings().fetchone()

            # Power stats
            power_result = await conn.execute(
                text("""
                    SELECT
                        COUNT(*) as reading_count,
                        MAX(COALESCE(power_sum_w, power_import_w)) as max_power_w,
                        AVG(COALESCE(power_sum_w, power_import_w)) as avg_power_w
                    FROM sma_readings
                    WHERE DATE(reading_time) = :date
                """),
                {"date": date_obj.isoformat()},
            )
            power_row = power_result.mappings().fetchone()

            energy_import_kwh = 0.0
            energy_export_kwh = 0.0

            if counter_row and counter_row["last_import"] is not None:
                energy_import_kwh = float(counter_row["last_import"] - counter_row["first_import"])
            if counter_row and counter_row["last_export"] is not None:
                energy_export_kwh = float(counter_row["last_export"] - counter_row["first_export"])

            await conn.execute(
                text("""
                    INSERT OR REPLACE INTO daily_energy_summary
                        (date, energy_import_kwh, energy_export_kwh,
                         max_power_w, avg_power_w, reading_count)
                    VALUES
                        (:date, :energy_import_kwh, :energy_export_kwh,
                         :max_power_w, :avg_power_w, :reading_count)
                """),
                {
                    "date": date_obj.isoformat(),
                    "energy_import_kwh": max(0.0, energy_import_kwh),
                    "energy_export_kwh": max(0.0, energy_export_kwh),
                    "max_power_w": power_row["max_power_w"] if power_row else None,
                    "avg_power_w": power_row["avg_power_w"] if power_row else None,
                    "reading_count": power_row["reading_count"] if power_row else 0,
                },
            )

    async def _refresh_hourly_pattern(self) -> None:
        """Rebuild the daily-pattern cache."""
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM hourly_pattern"))
            await conn.execute(
                text("""
                    INSERT INTO hourly_pattern
                        (time_slot, avg_power_import_w, avg_power_sum_w, sample_count)
                    SELECT
                        strftime('%H:%M', reading_time) as time_slot,
                        AVG(power_import_w) as avg_power_import_w,
                        AVG(COALESCE(power_sum_w, power_import_w)) as avg_power_sum_w,
                        COUNT(*) as sample_count
                    FROM sma_readings
                    WHERE COALESCE(power_sum_w, power_import_w) IS NOT NULL
                    GROUP BY strftime('%H:%M', reading_time)
                    HAVING COUNT(*) >= 5
                """)
            )
        logger.info("Hourly pattern refreshed")

    async def _log_connection(self, success: bool, error_message: str | None = None) -> None:
        """Log a connection attempt to the database."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO connection_log (polled_at, success, error_message)
                    VALUES (datetime('now'), :success, :error)
                """),
                {"success": success, "error": error_message},
            )
