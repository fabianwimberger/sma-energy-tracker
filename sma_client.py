#!/usr/bin/env python3
"""Smart Meter Adapter (SMA) HTTP API client."""

import logging
import ssl
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_ENDPOINT_MEASUREMENT = "/api/data/measurement.json"
API_ENDPOINT_STATUS = "/api/sma/status.json"
TIMEOUT_READ = 15.0


class SmaApiError(Exception):
    """Error communicating with Smart Meter Adapter."""


class SmaApiClient:
    """Client for the SMA JSON API."""

    def __init__(
        self,
        host: str,
        token: str,
        *,
        use_https: bool = True,
        verify_ssl: bool = False,
    ) -> None:
        self._host = host
        self._token = token
        self._use_https = use_https
        self._verify_ssl = verify_ssl

        proto = "https" if use_https else "http"
        self._base_url = f"{proto}://{host}"

        ssl_context: ssl.SSLContext | None
        if not verify_ssl and use_https:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        else:
            ssl_context = ssl.create_default_context() if verify_ssl else None

        self._client = httpx.AsyncClient(
            verify=ssl_context if ssl_context is not None else verify_ssl,
            timeout=httpx.Timeout(TIMEOUT_READ),
        )

    @property
    def host(self) -> str:
        return self._host

    def _headers(self) -> dict[str, str]:
        return {"AuthorizationToken": self._token}

    async def close(self) -> None:
        await self._client.aclose()

    async def validate_connection(self) -> bool:
        """Validate we can connect to the SMA."""
        try:
            data = await self._get_json(API_ENDPOINT_MEASUREMENT)
            return isinstance(data, dict) and len(data) > 0
        except SmaApiError:
            return False

    async def read_measurement(self) -> dict[str, Any]:
        """Read measurement data from the SMA."""
        data: dict[str, Any] = await self._get_json(API_ENDPOINT_MEASUREMENT)
        return data

    async def read_status(self) -> dict[str, str]:
        """Read status info (firmware, serial, etc.)."""
        result: dict[str, str] = {}
        try:
            data = await self._get_json(API_ENDPOINT_STATUS)
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, str | int | float):
                        result[key] = str(value)
                    elif isinstance(value, dict):
                        for sub_key, sub_value in value.items():
                            if isinstance(sub_value, str | int | float):
                                result[f"{key}.{sub_key}"] = str(sub_value)
        except SmaApiError:
            logger.debug("Status endpoint not available")
        return result

    async def _get_json(self, endpoint: str) -> Any:
        """Perform a GET request and return the JSON response."""
        url = f"{self._base_url}{endpoint}"
        try:
            response = await self._client.get(url, headers=self._headers())
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as err:
            raise SmaApiError(f"HTTP {err.response.status_code} from {endpoint}") from err
        except httpx.RequestError as err:
            raise SmaApiError(f"Connection error: {err}") from err


def extract_reading(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract relevant OBIS values from measurement data.

    Returns a dict with power and energy readings, or None if required
    fields are missing.
    """
    if not isinstance(data, dict):
        return None

    def _get_value(obis: str) -> float | None:
        entry = data.get(obis)
        if isinstance(entry, dict):
            return entry.get("value")
        return None

    power_sum = _get_value("1-0:16.7.0")
    power_import = _get_value("1-0:1.7.0")
    power_export = _get_value("1-0:2.7.0")
    energy_import_wh = _get_value("1-0:1.8.0")
    energy_export_wh = _get_value("1-0:2.8.0")

    if power_sum is None and power_import is None:
        return None

    return {
        "power_import_w": power_import,
        "power_export_w": power_export,
        "power_sum_w": power_sum,
        "energy_import_total_kwh": (energy_import_wh * 0.001)
        if energy_import_wh is not None
        else None,
        "energy_export_total_kwh": (energy_export_wh * 0.001)
        if energy_export_wh is not None
        else None,
    }
