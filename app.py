#!/usr/bin/env python3
"""SMA Energy Tracker — dashboard for Smart Meter Adapter data."""

import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import aiofiles  # type: ignore[import-untyped]
import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from db_init import init_database
from sma_client import SmaApiClient
from sma_poller import SmaPoller

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Configuration
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DATA_DIR}/sma_energy_data.db")
STATIC_DIR = Path(os.getenv("STATIC_DIR", "/app/static"))

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

SMA_HOST = os.getenv("SMA_HOST")
SMA_TOKEN = os.getenv("SMA_TOKEN")
SMA_USE_HTTPS = os.getenv("SMA_USE_HTTPS", "true").lower() in ("1", "true", "yes")
SMA_VERIFY_SSL = os.getenv("SMA_VERIFY_SSL", "false").lower() in ("1", "true", "yes")
SMA_POLL_INTERVAL = int(os.getenv("SMA_POLL_INTERVAL", "30"))


db_context: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    await init_database(engine)
    db_context["engine"] = engine

    # Start SMA poller if configured
    if SMA_HOST and SMA_TOKEN:
        client = SmaApiClient(
            host=SMA_HOST,
            token=SMA_TOKEN,
            use_https=SMA_USE_HTTPS,
            verify_ssl=SMA_VERIFY_SSL,
        )
        poller = SmaPoller(
            client=client,
            engine=engine,
            poll_interval=SMA_POLL_INTERVAL,
        )
        await poller.start()
        db_context["poller"] = poller
        logger.info("SMA poller initialized for %s", SMA_HOST)
    else:
        logger.warning(
            "SMA_HOST or SMA_TOKEN not set; poller will not start. "
            "Set both environment variables to enable live data collection."
        )

    yield

    if "poller" in db_context:
        await db_context["poller"].stop()
    await engine.dispose()
    logger.info("Database engine disposed.")


app = FastAPI(
    title="SMA Energy Tracker",
    description="Web application for visualizing Smart Meter Adapter data.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
api_router = APIRouter(prefix="/api")


class ChartData(BaseModel):
    labels: list[str]
    data: list[float]
    export_data: list[float] | None = None
    moving_average: list[float | None] | None = None
    daily_average_pattern: list[float] | None = None
    forecast: list[float | None] | None = None


class SmaStatus(BaseModel):
    configured: bool
    host: str | None = None
    connected: bool
    last_poll: str | None = None
    last_error: str | None = None
    total_readings: int = 0


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def get_frontend():
    try:
        async with aiofiles.open(STATIC_DIR / "index.html", encoding="utf-8") as f:
            content = await f.read()
            return HTMLResponse(content=content)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Error: index.html not found.</h1>", status_code=404)


async def _fetch_data(engine, query: str, params: dict[str, Any] | None = None):
    """Fetch data from the database."""
    async with engine.connect() as conn:
        result = await conn.execute(text(query), params or {})
        return result.mappings().fetchall()


@api_router.get("/chart-data", response_model=ChartData)
async def get_chart_data(
    aggregation: Literal["raw", "daily", "weekly", "monthly", "yearly"] = Query("daily"),
    day: date | None = None,
):
    try:
        if aggregation == "raw":
            if not day:
                raise HTTPException(
                    status_code=400,
                    detail="A 'day' parameter is required for raw aggregation.",
                )

            daily_query = """
                SELECT strftime('%H:%M:%S', reading_time) as label,
                       COALESCE(power_sum_w, power_import_w) as value,
                       power_import_w as import_value
                FROM sma_readings
                WHERE DATE(reading_time) = :day
                ORDER BY reading_time
            """

            pattern_query = """
                SELECT time_slot, avg_power_sum_w
                FROM hourly_pattern
                ORDER BY time_slot
            """

            daily_rows = await _fetch_data(db_context["engine"], daily_query, {"day": day})
            pattern_rows = await _fetch_data(db_context["engine"], pattern_query)

            if not daily_rows:
                return ChartData(labels=[], data=[], daily_average_pattern=[])

            pattern_map = {row["time_slot"]: float(row["avg_power_sum_w"]) for row in pattern_rows}

            return ChartData(
                labels=[row["label"] for row in daily_rows],
                data=[float(row["value"]) if row["value"] is not None else 0 for row in daily_rows],
                daily_average_pattern=[pattern_map.get(row["label"][:5], 0) for row in daily_rows],
            )

        elif aggregation == "daily":
            query = """
                SELECT date as label,
                       energy_import_kwh as value,
                       energy_export_kwh as export_value,
                       AVG(energy_import_kwh) OVER (
                           ORDER BY date
                           ROWS BETWEEN 45 PRECEDING AND 44 FOLLOWING
                       ) as moving_average
                FROM daily_energy_summary
                ORDER BY date
            """

            rows = await _fetch_data(db_context["engine"], query)

            if not rows:
                return ChartData(labels=[], data=[], moving_average=[])

            return ChartData(
                labels=[row["label"] for row in rows],
                data=[float(row["value"]) for row in rows],
                export_data=[float(row["export_value"]) for row in rows],
                moving_average=[
                    float(row["moving_average"]) if row["moving_average"] else None for row in rows
                ],
            )

        elif aggregation == "weekly":
            query = """
                SELECT strftime('%Y-W%W', date) as label,
                       strftime('%Y-%W', date) as sort_key,
                       SUM(energy_import_kwh) as value,
                       SUM(energy_export_kwh) as export_value,
                       COUNT(*) as day_count,
                       AVG(SUM(energy_import_kwh)) OVER (
                           ORDER BY strftime('%Y-%W', date)
                           ROWS BETWEEN 2 PRECEDING AND 2 FOLLOWING
                       ) as moving_average
                FROM daily_energy_summary
                GROUP BY strftime('%Y-%W', date)
                ORDER BY strftime('%Y-%W', date)
            """

            rows = await _fetch_data(db_context["engine"], query)

            current_date = datetime.now().date()
            current_week = current_date.strftime("%Y-%W")

            forecast_values: list[float | None] = []
            for row in rows:
                if row["sort_key"] == current_week:
                    days_in_week = 7
                    actual_days = int(row["day_count"])
                    if actual_days < days_in_week:
                        avg_per_day = float(row["value"]) / actual_days
                        forecast = avg_per_day * days_in_week
                        forecast_values.append(forecast)
                    else:
                        forecast_values.append(None)
                else:
                    forecast_values.append(None)

            return ChartData(
                labels=[row["label"] for row in rows],
                data=[float(row["value"]) for row in rows],
                export_data=[float(row["export_value"]) for row in rows],
                moving_average=[
                    float(row["moving_average"]) if row["moving_average"] else None for row in rows
                ],
                forecast=forecast_values,
            )

        elif aggregation == "monthly":
            query = """
                SELECT strftime('%Y-%m', date) as label,
                       SUM(energy_import_kwh) as value,
                       SUM(energy_export_kwh) as export_value,
                       COUNT(*) as day_count,
                       AVG(SUM(energy_import_kwh)) OVER (
                           ORDER BY strftime('%Y-%m', date)
                           ROWS BETWEEN 2 PRECEDING AND 2 FOLLOWING
                       ) as moving_average
                FROM daily_energy_summary
                GROUP BY strftime('%Y-%m', date)
                ORDER BY strftime('%Y-%m', date)
            """

            rows = await _fetch_data(db_context["engine"], query)

            current_date = datetime.now().date()
            current_month = current_date.strftime("%Y-%m")

            forecast_values = []
            for row in rows:
                if row["label"] == current_month:
                    year, month = map(int, row["label"].split("-"))
                    if month == 12:
                        next_month_date = datetime(year + 1, 1, 1).date()
                    else:
                        next_month_date = datetime(year, month + 1, 1).date()
                    days_in_month = (next_month_date - datetime(year, month, 1).date()).days

                    actual_days = int(row["day_count"])
                    if actual_days < days_in_month:
                        avg_per_day = float(row["value"]) / actual_days
                        forecast = avg_per_day * days_in_month
                        forecast_values.append(forecast)
                    else:
                        forecast_values.append(None)
                else:
                    forecast_values.append(None)

            return ChartData(
                labels=[row["label"] for row in rows],
                data=[float(row["value"]) for row in rows],
                export_data=[float(row["export_value"]) for row in rows],
                moving_average=[
                    float(row["moving_average"]) if row["moving_average"] else None for row in rows
                ],
                forecast=forecast_values,
            )

        else:  # yearly
            query = """
                SELECT strftime('%Y', date) as label,
                       SUM(energy_import_kwh) as value,
                       SUM(energy_export_kwh) as export_value,
                       COUNT(*) as day_count,
                       AVG(SUM(energy_import_kwh)) OVER (
                           ORDER BY strftime('%Y', date)
                           ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING
                       ) as moving_average
                FROM daily_energy_summary
                GROUP BY strftime('%Y', date)
                ORDER BY strftime('%Y', date)
            """

            rows = await _fetch_data(db_context["engine"], query)

            current_date = datetime.now().date()
            current_year = current_date.strftime("%Y")

            forecast_values = []
            for row in rows:
                if row["label"] == current_year:
                    year = int(row["label"])
                    days_in_year = (
                        366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
                    )

                    actual_days = int(row["day_count"])
                    if actual_days < days_in_year:
                        avg_per_day = float(row["value"]) / actual_days
                        forecast = avg_per_day * days_in_year
                        forecast_values.append(forecast)
                    else:
                        forecast_values.append(None)
                else:
                    forecast_values.append(None)

            return ChartData(
                labels=[row["label"] for row in rows],
                data=[float(row["value"]) for row in rows],
                export_data=[float(row["export_value"]) for row in rows],
                moving_average=[
                    float(row["moving_average"]) if row["moving_average"] else None for row in rows
                ],
                forecast=forecast_values,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database error") from e


@api_router.get("/latest-date")
async def get_latest_data_date():
    """Returns the date of the most recent reading in the database."""
    query = "SELECT DATE(MAX(reading_time)) as latest_date FROM sma_readings"
    rows = await _fetch_data(db_context["engine"], query)
    data = rows[0] if rows else None
    return {"latest_date": data["latest_date"] if data and data["latest_date"] else None}


@api_router.get("/stats")
async def get_database_stats():
    """Get database statistics for monitoring."""
    query = """
        SELECT
            (SELECT COUNT(*) FROM sma_readings) as total_readings,
            (SELECT COUNT(*) FROM daily_energy_summary) as total_days,
            (SELECT MIN(date) FROM daily_energy_summary) as first_date,
            (SELECT MAX(date) FROM daily_energy_summary) as last_date,
            (SELECT COUNT(*) FROM connection_log WHERE success = 1) as successful_polls,
            (SELECT COUNT(*) FROM connection_log WHERE success = 0) as failed_polls
    """
    rows = await _fetch_data(db_context["engine"], query)
    return rows[0] if rows else {}


@api_router.get("/sma-status", response_model=SmaStatus)
async def get_sma_status():
    """Get SMA connection status."""
    configured = bool(SMA_HOST and SMA_TOKEN)

    if not configured:
        return SmaStatus(configured=False, connected=False)

    engine = db_context["engine"]

    # Get latest connection log entry
    log_query = """
        SELECT polled_at, success, error_message
        FROM connection_log
        ORDER BY polled_at DESC
        LIMIT 1
    """
    log_rows = await _fetch_data(engine, log_query)
    log_entry = log_rows[0] if log_rows else None

    # Get total readings
    count_query = "SELECT COUNT(*) as c FROM sma_readings"
    count_rows = await _fetch_data(engine, count_query)
    total_readings = count_rows[0]["c"] if count_rows else 0

    return SmaStatus(
        configured=True,
        host=SMA_HOST,
        connected=log_entry["success"] if log_entry else False,
        last_poll=log_entry["polled_at"] if log_entry else None,
        last_error=log_entry["error_message"] if log_entry else None,
        total_readings=total_readings,
    )


app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
