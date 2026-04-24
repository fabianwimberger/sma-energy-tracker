"""Tests for FastAPI application endpoints."""


class TestRootEndpoint:
    def test_returns_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_security_headers_present(self, client):
        response = client.get("/")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"


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
