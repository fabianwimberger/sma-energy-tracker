#!/usr/bin/env python3
"""Background poller for the Smart Meter Adapter."""

import asyncio
import contextlib
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sma_client import SmaApiClient, SmaApiError, extract_reading

logger = logging.getLogger(__name__)
HOURLY_PATTERN_REFRESH_INTERVAL = timedelta(hours=1)
LOCAL_TZ = ZoneInfo(__import__("os").getenv("TZ", "Europe/Vienna"))


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
        self._today_date: date | None = None
        self._today_first_import: float | None = None
        self._today_first_export: float | None = None
        self._today_last_import: float | None = None
        self._today_last_export: float | None = None
        self._today_power_sum: float = 0.0
        self._today_power_max: float = 0.0
        self._today_reading_count: int = 0

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
            now = datetime.now(UTC)
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
        now = datetime.now(UTC)
        local_now = now.astimezone(LOCAL_TZ)
        reading_date_local = local_now.date().isoformat()
        time_slot_local = local_now.strftime("%H:%M")

        async with self.engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT OR REPLACE INTO sma_readings
                        (reading_time, reading_date_local, time_slot_local,
                         power_import_w, power_export_w, power_sum_w,
                         energy_import_total_kwh, energy_export_total_kwh)
                    VALUES
                        (:reading_time, :reading_date_local, :time_slot_local,
                         :power_import_w, :power_export_w, :power_sum_w,
                         :energy_import_total_kwh, :energy_export_total_kwh)
                """),
                {
                    "reading_time": now,
                    "reading_date_local": reading_date_local,
                    "time_slot_local": time_slot_local,
                    "power_import_w": reading.get("power_import_w"),
                    "power_export_w": reading.get("power_export_w"),
                    "power_sum_w": reading.get("power_sum_w"),
                    "energy_import_total_kwh": reading.get("energy_import_total_kwh"),
                    "energy_export_total_kwh": reading.get("energy_export_total_kwh"),
                },
            )

        # Refresh daily summary for today (local date)
        today_local = local_now.date()
        power = reading.get("power_sum_w") or reading.get("power_import_w") or 0.0
        energy_import = reading.get("energy_import_total_kwh")
        energy_export = reading.get("energy_export_total_kwh")

        if self._today_date != today_local:
            # New day or cold start: do full recompute once to ensure correctness
            stats = await self._refresh_daily_summary(today_local)
            self._today_date = today_local
            self._today_first_import = stats.get("first_import")
            self._today_first_export = stats.get("first_export")
            self._today_last_import = stats.get("last_import")
            self._today_last_export = stats.get("last_export")
            self._today_reading_count = stats.get("reading_count", 0)
            self._today_power_max = stats.get("max_power_w") or 0.0
            avg_power = stats.get("avg_power_w") or 0.0
            self._today_power_sum = avg_power * self._today_reading_count
        else:
            # Same day: incremental update to avoid full aggregate scans
            if energy_import is not None:
                if self._today_first_import is None:
                    self._today_first_import = energy_import
                self._today_last_import = energy_import
            if energy_export is not None:
                if self._today_first_export is None:
                    self._today_first_export = energy_export
                self._today_last_export = energy_export

            self._today_reading_count += 1
            self._today_power_sum += power
            if power > self._today_power_max:
                self._today_power_max = power

            energy_import_kwh = 0.0
            energy_export_kwh = 0.0
            if self._today_last_import is not None and self._today_first_import is not None:
                energy_import_kwh = max(
                    0.0, float(self._today_last_import - self._today_first_import)
                )
            if self._today_last_export is not None and self._today_first_export is not None:
                energy_export_kwh = max(
                    0.0, float(self._today_last_export - self._today_first_export)
                )

            avg_power = (
                self._today_power_sum / self._today_reading_count
                if self._today_reading_count > 0
                else 0.0
            )

            async with self.engine.begin() as conn:
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
                        "date": today_local.isoformat(),
                        "energy_import_kwh": energy_import_kwh,
                        "energy_export_kwh": energy_export_kwh,
                        "max_power_w": self._today_power_max if self._today_power_max > 0 else None,
                        "avg_power_w": avg_power if avg_power > 0 else None,
                        "reading_count": self._today_reading_count,
                    },
                )

    async def _refresh_daily_summary(self, date_local: date) -> dict[str, Any]:
        """Recalculate daily summary for a given local date using counter deltas.
        Returns the computed stats for incremental caching."""
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
                    WHERE reading_date_local = :date
                      AND energy_import_total_kwh IS NOT NULL
                """),
                {"date": date_local.isoformat()},
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
                    WHERE reading_date_local = :date
                """),
                {"date": date_local.isoformat()},
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
                    "date": date_local.isoformat(),
                    "energy_import_kwh": max(0.0, energy_import_kwh),
                    "energy_export_kwh": max(0.0, energy_export_kwh),
                    "max_power_w": power_row["max_power_w"] if power_row else None,
                    "avg_power_w": power_row["avg_power_w"] if power_row else None,
                    "reading_count": power_row["reading_count"] if power_row else 0,
                },
            )

        return {
            "first_import": counter_row["first_import"] if counter_row else None,
            "last_import": counter_row["last_import"] if counter_row else None,
            "first_export": counter_row["first_export"] if counter_row else None,
            "last_export": counter_row["last_export"] if counter_row else None,
            "reading_count": power_row["reading_count"] if power_row else 0,
            "max_power_w": power_row["max_power_w"] if power_row else None,
            "avg_power_w": power_row["avg_power_w"] if power_row else None,
        }

    async def _refresh_hourly_pattern(self) -> None:
        """Rebuild the daily-pattern cache from local time slots."""
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM hourly_pattern"))
            await conn.execute(
                text("""
                    INSERT INTO hourly_pattern
                        (time_slot, avg_power_import_w, avg_power_sum_w, sample_count)
                    SELECT
                        time_slot_local as time_slot,
                        AVG(power_import_w) as avg_power_import_w,
                        AVG(COALESCE(power_sum_w, power_import_w)) as avg_power_sum_w,
                        COUNT(*) as sample_count
                    FROM sma_readings
                    WHERE COALESCE(power_sum_w, power_import_w) IS NOT NULL
                      AND time_slot_local IS NOT NULL
                    GROUP BY time_slot_local
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
                    VALUES (:polled_at, :success, :error)
                """),
                {
                    "polled_at": datetime.now(UTC),
                    "success": success,
                    "error": error_message,
                },
            )
