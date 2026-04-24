"""Tests for SMA API client."""

from sma_client import extract_reading


class TestExtractReading:
    def test_extracts_all_fields(self):
        data = {
            "1-0:1.7.0": {"value": 1500},
            "1-0:2.7.0": {"value": 0},
            "1-0:16.7.0": {"value": 1500},
            "1-0:1.8.0": {"value": 12345000},
            "1-0:2.8.0": {"value": 500000},
        }
        result = extract_reading(data)
        assert result is not None
        assert result["power_import_w"] == 1500
        assert result["power_export_w"] == 0
        assert result["power_sum_w"] == 1500
        assert result["energy_import_total_kwh"] == 12345.0
        assert result["energy_export_total_kwh"] == 500.0

    def test_returns_none_when_no_power_data(self):
        data = {
            "1-0:1.8.0": {"value": 12345000},
        }
        result = extract_reading(data)
        assert result is None

    def test_handles_missing_optional_fields(self):
        data = {
            "1-0:16.7.0": {"value": 1500},
        }
        result = extract_reading(data)
        assert result is not None
        assert result["power_sum_w"] == 1500
        assert result["power_import_w"] is None
        assert result["energy_import_total_kwh"] is None

    def test_handles_non_dict_input(self):
        assert extract_reading(None) is None
        assert extract_reading("string") is None
        assert extract_reading(42) is None
