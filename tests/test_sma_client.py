"""Tests for SMA API client."""

from sma_client import extract_reading


class TestExtractReading:
    def test_extracts_all_fields(self):
        data = {
            "1-0:1.7.0": {"value": 1500},
            "1-0:2.7.0": {"value": 0},
            "1-0:16.7.0": {"value": 1500},
            "1-0:1.8.0": {"value": 12345000, "unit": "Wh"},
            "1-0:2.8.0": {"value": 500000, "unit": "Wh"},
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

    def test_uses_energy_units(self):
        data = {
            "1-0:16.7.0": {"value": 1500},
            "1-0:1.8.0": {"value": 12.5, "unit": "kWh"},
            "1-0:2.8.0": {"value": 0.5, "unit": "MWh"},
        }
        result = extract_reading(data)
        assert result is not None
        assert result["energy_import_total_kwh"] == 12.5
        assert result["energy_export_total_kwh"] == 500

    def test_handles_numeric_strings_without_units(self):
        data = {
            "1-0:1.7.0": {"value": "1"},
            "1-0:2.7.0": {"value": "0"},
            "1-0:1.8.0": {"value": "9036549"},
            "1-0:2.8.0": {"value": "62578"},
        }
        result = extract_reading(data)
        assert result is not None
        assert result["power_import_w"] == 1.0
        assert result["power_export_w"] == 0.0
        assert result["power_sum_w"] == 1.0
        assert result["energy_import_total_kwh"] == 9036.549
        assert result["energy_export_total_kwh"] == 62.578

    def test_handles_non_dict_input(self):
        assert extract_reading(None) is None
        assert extract_reading("string") is None
        assert extract_reading(42) is None
