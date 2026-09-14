<div align="center">

# AeroTrack

**Hourly Google Flights price intelligence for Indian domestic routes.**
Self-hosted · Dockerized · Coolify-ready · Bright Data IP Protection

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white&style=flat-square)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.14-009688?logo=fastapi&logoColor=white&style=flat-square)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white&style=flat-square)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-6366f1?style=flat-square)](LICENSE)

</div>

---

AeroTrack scrapes **Google Flights** every hour using [`AWeirdDev/flights`](https://github.com/AWeirdDev/flights) (`fast-flights`) and logs the **cheapest available fare** for each tracked route — recording airline, price, timing, duration, stops, and plane type to a local SQLite database. A slick dark-themed dashboard gives you interactive price graphs, route cards, and a full log history.

---

## Dashboard

> Live data, hourly updates, BrightData IP protection status — all in one view.

| Route Cards | Price Chart | Log History |
|:-----------:|:-----------:|:-----------:|
| Current cheapest fare per route with trend indicator | Time-series chart with 24h/3d/7d/30d view | Full searchable history with all-flights breakdown |

---

## Features

- **4 Predefined Indian Routes** — HYD to/from PNQ, HYD to/from BOM (fully configurable)
- **Hourly Automated Scraping** — APScheduler embedded in FastAPI
- **Bright Data IP Protection** — Uses `fast_flights.integrations.BrightData` to route requests through Bright Data's SERP zone; falls back to direct mode gracefully
- **Interactive Price Chart** — Chart.js powered time-series with route filtering
- **Tabbed Dashboard** — Dashboard / Log History / Analytics views
- **Full Flight Breakdowns** — Every scrape stores all candidate flights, not just the cheapest
- **One-Click CSV Export** — Download your entire history as a spreadsheet
- **Single Docker Container** — Python 3.12 slim image, SQLite volume, healthcheck
- **REST API** — 8 documented endpoints ready for integrations

---

## Quick Start (Local)

```bash
# Clone
git clone https://github.com/RoomTempratureWater/AeroTrack.git
cd AeroTrack

# Setup environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — add BRIGHT_DATA_API_KEY if you have one

# Run
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** — a scrape will start automatically on launch.

---

## Deploy with Docker

```bash
docker compose up -d
```

The app starts, initialises the SQLite database, and begins its hourly schedule.

```yaml
# Persistent storage — your data survives container updates
volumes:
  - flight_tracker_data:/app/data
```

---

## Coolify Deployment

1. **Add Resource** -> Git Repository -> point to this repo
2. **Build Pack** -> `Dockerfile`  |  **Port** -> `8000`
3. **Storages** tab -> add persistent volume:
   - Volume name: `flight_tracker_data`
   - Mount path: `/app/data`
4. **Environment Variables**:

```env
PORT=8000
CHECK_INTERVAL_MINUTES=60
RUN_SCRAPE_ON_STARTUP=true
DEFAULT_CURRENCY=INR

# Bright Data (get from brightdata.com)
BRIGHT_DATA_API_KEY=your_key_here
BRIGHT_DATA_ZONE=serp_api1
```

5. **Deploy** — Coolify assigns a domain, healthcheck validates `/health`, you're live.

---

## Bright Data Integration

AeroTrack uses the native [`fast_flights.integrations.BrightData`](https://github.com/AWeirdDev/flights#bright-data) integration to protect your IP from Google's rate limiting:

```python
from fast_flights.integrations import BrightData
result = get_flights(query, integration=BrightData(api_key="...", zone="serp_api1"))
```

**Setup:**
1. Sign up at [brightdata.com](https://brightdata.com) -> create a **SERP API** zone
2. Copy your API key from *Account Settings -> API Keys*
3. Set `BRIGHT_DATA_API_KEY` in your `.env` or Coolify environment variables
4. The dashboard header shows a green **"BrightData Protected"** badge when active

> **No key?** AeroTrack works without Bright Data in direct mode for personal/dev use — the dashboard clearly shows "Direct Mode" status.

---

## REST API

| Method | Endpoint | Description |
|:------:|:---------|:------------|
| `GET`  | `/`               | Interactive dashboard |
| `GET`  | `/health`         | Container healthcheck (used by Coolify) |
| `GET`  | `/api/status`     | Scheduler, BrightData status, total records |
| `GET`  | `/api/routes`     | All routes with latest price + trend |
| `GET`  | `/api/history`    | Time-series points for charting (`?days=7&route_code=HYD-PNQ`) |
| `GET`  | `/api/stats`      | Min/avg/max and top carrier per route |
| `GET`  | `/api/logs`       | Paginated historical logs (`?limit=20&offset=0`) |
| `POST` | `/api/scrape/trigger` | Trigger an immediate scrape cycle |
| `GET`  | `/api/export`     | Download complete history as CSV |

---

## Project Structure

```
AeroTrack/
├── app/
│   ├── config.py           # Pydantic settings (env vars)
│   ├── database.py         # Async SQLAlchemy engine
│   ├── models.py           # FlightLog + ScrapeJobRun tables
│   ├── scraper.py          # fast-flights + BrightData + safe parser
│   ├── scheduler.py        # APScheduler hourly job
│   ├── api.py              # All REST endpoints
│   ├── main.py             # FastAPI app entrypoint
│   ├── static/
│   │   ├── css/styles.css  # Dark theme design system
│   │   └── js/app.js       # Dashboard frontend controller
│   └── templates/
│       └── index.html      # Jinja2 HTML dashboard
├── data/                   # SQLite DB lives here (Docker volume)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Configuration Reference

| Variable | Default | Description |
|:---------|:--------|:------------|
| `PORT` | `8000` | Server port |
| `CHECK_INTERVAL_MINUTES` | `60` | How often to scrape |
| `RUN_SCRAPE_ON_STARTUP` | `true` | Run a scrape immediately on launch |
| `TRACK_DATE_MODE` | `today` | `today`, `tomorrow`, or `both` |
| `DEFAULT_CURRENCY` | `INR` | Display currency |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/flights.db` | SQLAlchemy database URL |
| `BRIGHT_DATA_API_KEY` | *(empty)* | Bright Data API key for IP protection |
| `BRIGHT_DATA_ZONE` | `serp_api1` | Bright Data zone name |
| `BRIGHT_DATA_PROXY_URL` | *(empty)* | Alternative: standard proxy URL |

---

## How It Works

```
APScheduler (every 60m)
        |
        v
  app/scraper.py
  fast-flights lib  <--  BrightData zone (optional)
  Google Flights RPC
        |
        v  Returns list of flights
  Find cheapest fare
  Save to SQLite
        |
        v
  FastAPI REST API  <--  Dashboard frontend
  /api/routes            Chart.js + Tailwind
  /api/history
```

---

## License

MIT — use freely, self-host forever.

---

<div align="center">
Built with care · Powered by <a href="https://github.com/AWeirdDev/flights">AWeirdDev/flights</a>
</div>
