"""Tests for FastAPI application endpoints."""

import asyncio

from sqlalchemy import text

import app as app_module


class TestRootEndpoint:
    def test_returns_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_security_headers_present(self, client):
        response = client.get("/")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"


class TestHealthzEndpoint:
    def test_returns_ok(self, client):
        response = client.get("/api/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestLatestDateEndpoint:
    def test_returns_json(self, client):
        response = client.get("/api/latest-date")
        assert response.status_code == 200
        assert response.json() == {"latest_date": None}


class TestStatsEndpoint:
    def test_returns_zero_stats_for_empty_db(self, client):
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_readings"] == 0
        assert data["total_days"] == 0
        assert data["successful_polls"] == 0
        assert data["failed_polls"] == 0


class TestSmaStatusEndpoint:
    def test_returns_not_configured_when_no_env(self, client):
        response = client.get("/api/sma-status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False
        assert data["connected"] is False

    def test_returns_last_poll_in_configured_timezone(self, client):
        async def insert_connection_log():
            async with app_module.db_context["engine"].begin() as conn:
                await conn.execute(
                    text("""
                        INSERT INTO connection_log (polled_at, success, error_message)
                        VALUES ('2026-05-09 12:34:56', 1, NULL)
                    """)
                )

        old_host = app_module.SMA_HOST
        old_token = app_module.SMA_TOKEN
        app_module.SMA_HOST = "192.0.2.10"
        app_module.SMA_TOKEN = "test-token"

        try:
            asyncio.run(insert_connection_log())
            response = client.get("/api/sma-status")
        finally:
            app_module.SMA_HOST = old_host
            app_module.SMA_TOKEN = old_token

        assert response.status_code == 200
        data = response.json()
        assert data["timezone"] == "Europe/Vienna"
        assert data["last_poll"] == "2026-05-09T14:34:56+02:00"


class TestChartDataEndpoint:
    def test_daily_aggregation_empty(self, client):
        response = client.get("/api/chart-data?aggregation=daily")
        assert response.status_code == 200
        data = response.json()
        assert data["labels"] == []
        assert data["data"] == []

    def test_raw_requires_day(self, client):
        response = client.get("/api/chart-data?aggregation=raw")
        assert response.status_code == 400
        assert "day" in response.json()["detail"].lower()

    def test_invalid_aggregation(self, client):
        response = client.get("/api/chart-data?aggregation=invalid")
        assert response.status_code == 422

    def test_raw_with_day_empty(self, client):
        response = client.get("/api/chart-data?aggregation=raw&day=2025-01-01")
        assert response.status_code == 200
        data = response.json()
        assert data["labels"] == []
        assert data["data"] == []

    def test_raw_uses_local_date_and_time_labels(self, client):
        async def insert_reading():
            async with app_module.db_context["engine"].begin() as conn:
                await conn.execute(
                    text("""
                        INSERT INTO sma_readings
                            (reading_time, reading_date_local, time_slot_local, power_sum_w)
                        VALUES
                            ('2026-05-09 12:34:56+00:00', '2026-05-09', '14:34', 123.0)
                    """)
                )

        asyncio.run(insert_reading())

        response = client.get("/api/chart-data?aggregation=raw&day=2026-05-09")
        assert response.status_code == 200
        data = response.json()
        assert data["labels"] == ["14:34:56"]
        assert data["data"] == [123.0]

    def test_weekly_aggregation_empty(self, client):
        response = client.get("/api/chart-data?aggregation=weekly")
        assert response.status_code == 200
        data = response.json()
        assert data["labels"] == []
        assert data["data"] == []

    def test_monthly_aggregation_empty(self, client):
        response = client.get("/api/chart-data?aggregation=monthly")
        assert response.status_code == 200
        data = response.json()
        assert data["labels"] == []
        assert data["data"] == []

    def test_yearly_aggregation_empty(self, client):
        response = client.get("/api/chart-data?aggregation=yearly")
        assert response.status_code == 200
        data = response.json()
        assert data["labels"] == []
        assert data["data"] == []
