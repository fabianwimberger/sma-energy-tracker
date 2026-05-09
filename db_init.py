#!/usr/bin/env python3
"""Database schema initialization and migrations."""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2


async def init_database(engine: AsyncEngine):
    async with engine.connect() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=5000"))
        await conn.execute(text("PRAGMA synchronous=NORMAL"))
        await conn.execute(text("PRAGMA cache_size=-64000"))
        await conn.execute(text("PRAGMA temp_store=MEMORY"))

        # Check schema version
        await conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        )

        result = await conn.execute(text("SELECT MAX(version) as v FROM schema_version"))
        current_version = result.scalar() or 0

        if current_version < SCHEMA_VERSION:
            logger.info(f"Upgrading schema from {current_version} to {SCHEMA_VERSION}")
            await apply_migrations(conn, current_version)
            await conn.execute(
                text("INSERT INTO schema_version (version) VALUES (:v)"),
                {"v": SCHEMA_VERSION},
            )
            await conn.commit()


async def apply_migrations(conn, current_version):
    if current_version < 1:
        await conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS sma_readings (
                reading_time TIMESTAMP PRIMARY KEY,
                reading_date_local TEXT,
                time_slot_local TEXT,
                power_import_w REAL,
                power_export_w REAL,
                power_sum_w REAL,
                energy_import_total_kwh REAL,
                energy_export_total_kwh REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        )

        await conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS daily_energy_summary (
                date DATE PRIMARY KEY,
                energy_import_kwh REAL NOT NULL DEFAULT 0,
                energy_export_kwh REAL NOT NULL DEFAULT 0,
                max_power_w REAL,
                avg_power_w REAL,
                reading_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        )

        await conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS hourly_pattern (
                time_slot TEXT PRIMARY KEY,
                avg_power_import_w REAL NOT NULL,
                avg_power_sum_w REAL NOT NULL,
                sample_count INTEGER NOT NULL
            )
        """)
        )

        await conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS connection_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                polled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success BOOLEAN NOT NULL,
                error_message TEXT
            )
        """)
        )

        # Indexes
        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_readings_date_local
            ON sma_readings(reading_date_local)
        """)
        )

        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_readings_time_slot_local
            ON sma_readings(time_slot_local)
        """)
        )

        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_daily_date_desc
            ON daily_energy_summary(date DESC)
        """)
        )

        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_daily_year_week
            ON daily_energy_summary(strftime('%Y-%W', date))
        """)
        )

        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_daily_year_month
            ON daily_energy_summary(strftime('%Y-%m', date))
        """)
        )

        # updated_at trigger
        await conn.execute(
            text("""
            CREATE TRIGGER IF NOT EXISTS update_daily_summary_timestamp
            AFTER UPDATE ON daily_energy_summary
            BEGIN
                UPDATE daily_energy_summary SET updated_at = CURRENT_TIMESTAMP
                WHERE date = NEW.date;
            END
        """)
        )

    if current_version < 2:
        logger.info("Applying schema migration v2: local date/time columns")
        result = await conn.execute(text("PRAGMA table_info(sma_readings)"))
        columns = {row[1] for row in result.fetchall()}

        if "reading_date_local" not in columns:
            await conn.execute(
                text("ALTER TABLE sma_readings ADD COLUMN reading_date_local TEXT")
            )
        if "time_slot_local" not in columns:
            await conn.execute(
                text("ALTER TABLE sma_readings ADD COLUMN time_slot_local TEXT")
            )

        # Populate new columns for existing data (legacy reading_time is naive local time)
        await conn.execute(
            text("""
                UPDATE sma_readings
                SET reading_date_local = DATE(reading_time),
                    time_slot_local = strftime('%H:%M', reading_time)
                WHERE reading_date_local IS NULL
            """)
        )

        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_readings_date_local
            ON sma_readings(reading_date_local)
        """)
        )

        await conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_readings_time_slot_local
            ON sma_readings(time_slot_local)
        """)
        )

        # Drop legacy indexes that may exist from v1
        await conn.execute(text("DROP INDEX IF EXISTS idx_readings_date"))
        await conn.execute(text("DROP INDEX IF EXISTS idx_readings_time_hour_minute"))

        await conn.execute(text("ANALYZE"))
