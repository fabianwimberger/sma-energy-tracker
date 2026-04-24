# SMA Energy Tracker

[![CI](https://github.com/fabianwimberger/sma-energy-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/fabianwimberger/sma-energy-tracker/actions)
[![codecov](https://codecov.io/gh/fabianwimberger/sma-energy-tracker/branch/main/graph/badge.svg)](https://codecov.io/gh/fabianwimberger/sma-energy-tracker)
[![Docker](https://github.com/fabianwimberger/sma-energy-tracker/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/fabianwimberger/sma-energy-tracker/pkgs/container/sma-energy-tracker)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A self-hosted dashboard for visualizing electricity consumption directly from the
**Smart Meter Adapter (SMA)** by Österreichs E-Wirtschaft.

Unlike the original [energy-tracker](https://github.com/fabianwimberger/energy-tracker)
which imports CSV files, this application polls the SMA's JSON REST API directly —
no manual file handling required.

## Features

- **Live data collection** from Smart Meter Adapter via REST API
- **Quarter-hourly raw view** with your average daily load pattern overlaid
- **Daily / weekly / monthly / yearly** aggregations with moving averages
- **Simple linear forecast** for the current week, month, or year
- **Import & export tracking** (if your meter provides both counters)
- **SQLite** — no external database required
- **Dark-themed dashboard** with zoom, pan, and responsive layout

## Quick Start

### Option 1: Using Pre-built Image (Recommended)

Pre-built images support both **AMD64** and **ARM64** architectures.

**Docker Compose:**

```bash
# Clone the repository for docker-compose.yml
git clone https://github.com/fabianwimberger/sma-energy-tracker.git
cd sma-energy-tracker

# Create a .env file with your SMA credentials
cat > .env <<EOF
SMA_HOST=192.168.1.100
SMA_TOKEN=your-sma-api-token
SMA_USE_HTTPS=true
SMA_VERIFY_SSL=false
SMA_POLL_INTERVAL=30
EOF

# Run with pre-built image
docker compose up -d

# Open UI at http://localhost:8000
```

**Or with docker run:**

```bash
docker run -d \
  --name sma-energy-tracker \
  --restart unless-stopped \
  -p 8000:8000 \
  -v sma-energy-data:/app/data \
  -e TZ=Europe/Vienna \
  -e SMA_HOST=192.168.1.100 \
  -e SMA_TOKEN=your-sma-api-token \
  ghcr.io/fabianwimberger/sma-energy-tracker:latest
```

### Option 2: Build from Source

```bash
# Clone the repository
git clone https://github.com/fabianwimberger/sma-energy-tracker.git
cd sma-energy-tracker

# Copy the override file to build locally
cp docker-compose.override.yml.example docker-compose.override.yml

# Build and run
make build
make up

# Or using docker compose directly:
# docker compose build
# docker compose up -d

# Open UI at http://localhost:8000
```

### Available Image Tags

| Tag | Description |
|-----|-------------|
| `main` | Latest development build from main branch |
| `v1.2.3` | Specific release version |
| `v1.2` | Latest patch release in the v1.2.x series |
| `v1` | Latest minor release in the v1.x.x series |
| `<short-sha>` | Specific commit SHA |

### Updating

```bash
# Pull latest image
docker compose pull
docker compose up -d

# Or with docker run
docker pull ghcr.io/fabianwimberger/sma-energy-tracker:latest
docker restart sma-energy-tracker
```

## Configuration

All configuration is via environment variables.

### Required

| Variable | Description |
|----------|-------------|
| `SMA_HOST` | IP address or hostname of the Smart Meter Adapter |
| `SMA_TOKEN` | Authorization token from the SMA web UI (*API → JSON*) |

### Optional

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `8000` | Host port for the web UI |
| `TZ` | `Europe/Vienna` | Container timezone |
| `DATA_DIR` | `/app/data` | Directory for SQLite database |
| `DATABASE_URL` | derived | SQLAlchemy async URL (override for custom path) |
| `STATIC_DIR` | `/app/static` | Directory served at `/static` |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `SMA_USE_HTTPS` | `true` | Use HTTPS when connecting to SMA |
| `SMA_VERIFY_SSL` | `false` | Verify SSL certificate (disable for self-signed certs) |
| `SMA_POLL_INTERVAL` | `30` | Polling interval in seconds |

## Finding Your SMA Token

1. Open the SMA web interface in your browser (e.g. `https://192.168.1.100`)
2. Navigate to **API → JSON**
3. Copy the **Authorization Token** shown on that page
4. Use it as the `SMA_TOKEN` environment variable

## Production Deployment

The bundled `docker-compose.yml` is a minimal standalone setup. For production,
put reverse-proxy config, TLS, and auth in a local `docker-compose.override.yml`
(already gitignored), for example:

```yaml
services:
  app:
    ports: !reset []
    labels:
      - traefik.enable=true
      - traefik.http.routers.sma.rule=Host(`sma.example.com`)
      - traefik.http.routers.sma.tls.certresolver=letsencrypt
    networks:
      - reverse-proxy
    environment:
      CORS_ORIGINS: https://sma.example.com

networks:
  reverse-proxy:
    external: true
```

The app has no built-in authentication — put it behind something (OIDC proxy,
basic auth, Tailscale, etc.) before exposing it to the internet.

## How It Works

The application runs a background task that polls the SMA every
`SMA_POLL_INTERVAL` seconds. Each poll reads:

| OBIS Code | Meaning | Stored As |
|-----------|---------|-----------|
| `1-0:1.7.0` | Active power import | `power_import_w` |
| `1-0:2.7.0` | Active power export | `power_export_w` |
| `1-0:16.7.0` | Active power sum | `power_sum_w` |
| `1-0:1.8.0` | Total energy import | `energy_import_total_kwh` |
| `1-0:2.8.0` | Total energy export | `energy_export_total_kwh` |

Daily energy consumption is calculated from the **difference in cumulative
counters** between the first and last reading of each day. This is more
accurate than integrating instantaneous power, especially if some polls are
missed.

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
make setup        # Download vendor libraries
make test         # Run the test suite
make lint         # Run linters
make typecheck    # Run type checker
make format       # Format code

# Run locally (without SMA poller)
DATA_DIR=./data STATIC_DIR=./static python app.py

# Run locally with SMA polling
SMA_HOST=192.168.1.100 SMA_TOKEN=your-token DATA_DIR=./data STATIC_DIR=./static python app.py
```

## License

MIT — see [LICENSE](LICENSE).

### Third-Party Licenses

| Component | License | Source |
|-----------|---------|--------|
| Chart.js | [MIT](https://github.com/chartjs/Chart.js/blob/master/LICENSE) | https://github.com/chartjs/Chart.js |
| chartjs-plugin-zoom | [MIT](https://github.com/chartjs/chartjs-plugin-zoom/blob/master/LICENSE) | https://github.com/chartjs/chartjs-plugin-zoom |
| Flatpickr | [MIT](https://github.com/flatpickr/flatpickr/blob/master/LICENSE.md) | https://github.com/flatpickr/flatpickr |
