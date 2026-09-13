# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v1.4.0] - 2026-08-14

Python 3.14 base image plus routine backend dependency updates.

### Dependencies

- Base image `python:3.13-alpine` → `python:3.14-alpine`
- fastapi 0.139.0 → 0.141.1
- uvicorn 0.51.0 → 0.52.3
- sqlalchemy 2.0.51 → 2.0.52
- ruff 0.15.21 → 0.16.3
- mypy 2.2.0 → 2.3.0
- actions/setup-python 6 → 7

### Documentation & Links

- [README](https://github.com/fabianwimberger/sma-energy-tracker#readme)
- [Container image](https://github.com/fabianwimberger/sma-energy-tracker/pkgs/container/sma-energy-tracker)

## [v1.3.0] - 2026-07-18

A visual redesign of the dashboard, plus a chart interaction fix.

### Features

- Redesigned the dashboard with a warm, meter-inspired palette — copper for import, slate-blue for export, cyan for the moving average, gold for forecasts — replacing the generic dark-slate look.
- Self-hosted Space Grotesk and IBM Plex Mono typefaces, a custom Wi-Fi/live-signal icon replacing the emoji header icon, and a designed empty state for when there's no reading yet.

### Fixes

- Fixed the `<`/`>` chart pan buttons causing visible stutter on longer history.

### Documentation & Links

- Refreshed the dashboard screenshot to show the new interface.
- Third-party license table updated for the newly self-hosted fonts.

## [v1.2.0] - 2026-05-14

SMA Energy Tracker v1.2.0 adds direct chart controls for easier dashboard navigation.

### Features

- Added visible chart buttons for panning, zooming in, zooming out, and resetting the dashboard chart.
- Hid the raw-view average pattern by default so live SMA readings are easier to inspect.

### Documentation & Links

- Updated the dashboard screenshot for the new chart controls.
- Docker images are published to `ghcr.io/fabianwimberger/sma-energy-tracker` with the usual version tags.

## [v1.1.2] - 2026-05-09

User-facing time display fixes and faster default updates for the SMA dashboard.

### Fixes

- Show raw chart times from the configured local timezone instead of UTC
- Format SMA status timestamps in 24-hour time
- Use the configured app timezone for status time display
- Change the default SMA polling interval to 5 seconds
- Refresh dashboard status, stats, and chart data every 5 seconds

### Testing

- Lint, type checks, unit tests, and Docker builds passed on main
- Docker image publish completed successfully

### Documentation & Links

- [README](https://github.com/fabianwimberger/sma-energy-tracker#readme)
- [Container image](https://github.com/fabianwimberger/sma-energy-tracker/pkgs/container/sma-energy-tracker)

## [v1.1.1] - 2026-05-09

SMA measurement parsing fixes and data handling improvements for local energy tracking.

### Fixes

- Parse numeric string values from SMA measurement responses
- Keep Wh as the default for energy counters without unit metadata
- Store readings in UTC while grouping charts by local date and time slots
- Reduce daily-summary write amplification with incremental cache updates
- Add a lightweight health endpoint and safer default CORS origins

### Testing

- Lint, type checks, unit tests, and Docker builds passed on main
- Docker image publish completed successfully

### Documentation & Links

- [README](https://github.com/fabianwimberger/sma-energy-tracker#readme)
- [Container image](https://github.com/fabianwimberger/sma-energy-tracker/pkgs/container/sma-energy-tracker)

## [v1.1.0] - 2026-05-09

Timezone correctness and performance improvements.

### Fixes
- UTC timestamps with local date/time columns (schema v2) — eliminates DST duplicate-key collisions and gaps
- Day boundaries no longer mix container TZ vs SQLite UTC default
- Incremental in-memory daily summary cache — no full aggregate scan on every 30 s poll
- Indexes match actual query patterns (replaced expression indexes)
- Gated frontend polling — raw view polls every 5 s, aggregated views every 30 s
- Tightened CORS defaults; wildcard auto-disables credentials
- Dedicated /api/healthz endpoint (no DB I/O)
- Lazy % formatting for all loggers
- Fix lint errors from upgraded ruff (unused imports, datetime.UTC alias)

### Dependencies
- fastapi 0.136.1, uvicorn 0.46.0, pydantic 2.13.3, ruff 0.15.12, mypy 1.20.2

### Documentation & Links
- https://github.com/fabianwimberger/sma-energy-tracker

## [v1.0.0] - 2026-04-25

First official release. Self-hosted dashboard that polls the local Smart Meter Adapter (SMA) JSON REST API directly — no CSV imports, no manual file handling.

For historical CSV imports without a SMA device on the network, see the sister project [linznetz-energy-tracker](https://github.com/fabianwimberger/linznetz-energy-tracker).

### Features

- **Live data collection** from Smart Meter Adapter via REST
- **Quarter-hourly raw view** with your average daily load pattern overlaid (default view)
- **Daily / weekly / monthly / yearly** aggregations with moving averages
- **Live chart refresh** while you watch
- **Simple linear forecast** for the current week, month, or year
- **SQLite** — no external database required

### Quick Start

```bash
docker run -d \
  --name sma-energy-tracker \
  --restart unless-stopped \
  -p 8000:8000 \
  -v sma-energy-data:/app/data \
  -e TZ=Europe/Vienna \
  -e SMA_HOST=192.168.1.100 \
  -e SMA_TOKEN=your-sma-api-token \
  ghcr.io/fabianwimberger/sma-energy-tracker:1.0.0
```

Open the UI at **http://localhost:8000**.

### Notes

- Not affiliated with or endorsed by Österreichs E-Wirtschaft
- Requires a Smart Meter Adapter (SMA) reachable on the local network with API token enabled

### Documentation & Links

- [README](https://github.com/fabianwimberger/sma-energy-tracker#readme)
- [Container image](https://github.com/fabianwimberger/sma-energy-tracker/pkgs/container/sma-energy-tracker)
