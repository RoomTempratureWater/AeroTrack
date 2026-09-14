# ✈️ AeroTrack — Hourly Flight Price Intelligence

A self-hosted, Dockerized flight price tracker designed for single-click deployment on **Coolify**. It uses [`AWeirdDev/flights`](https://github.com/AWeirdDev/flights) (`fast-flights`) with native **Bright Data** IP protection to monitor Google Flights fares on predefined routes every hour and present price trajectories, lowest fare analytics, and full flight option breakdowns in a dashboard.

---

## 🌟 Features

- **Predefined Route Tracking**:
  - `HYD -> PNQ` (Hyderabad to Pune)
  - `PNQ -> HYD` (Pune to Hyderabad)
  - `BOM -> HYD` (Mumbai to Hyderabad)
  - `HYD -> BOM` (Hyderabad to Mumbai)
- **Hourly Automated Scraping**: Runs via an embedded `APScheduler` async engine to capture the cheapest fare of the day.
- **Bright Data IP Protection**:
  - Directly integrated with `fast_flights.integrations.BrightData` to route scraping requests through Bright Data's SERP API or Web Unlocker zone.
  - Supports standard proxy URLs (`http://user:pass@host:port`) as an alternative.
  - Safe fallback: If credentials are not set, it operates in direct mode for local development.
- **Cheapest Fare Logging**: Records timestamp, departure date, day of week, airline (IndiGo, Air India, Alliance Air, Akasa Air, etc.), departure/arrival timing, duration, stops, plane type, and full flight breakdowns.
- **Interactive Modern Dashboard**:
  - **Live Status Header**: Real-time Bright Data status pill, countdown to next check, manual "Check Now" trigger, and CSV export.
  - **Route Summary Cards**: Current lowest fare, 24h trend (drop/rise), airline badge, and all-time low.
  - **Time-Series Chart**: Interactive Chart.js graph plotting price trajectories across hours/days with 24h, 3d, 7d, and 30d views.
  - **Flight Breakdown Modal**: Click on any logged check to inspect all candidate flights captured during that scrape.
- **Zero-Orchestration Coolify Ready**: Single lightweight container (FastAPI + SQLite + Tailwind UI) with persistent volume support.

---

## 🚀 Deployment on Coolify

Deploying on Coolify is straightforward. You can deploy it using either the **Dockerfile** or **Docker Compose**.

### Method 1: Deploy via Coolify Web Interface (Recommended)

1. **Create New Resource in Coolify**:
   - Go to your Project / Environment in Coolify.
   - Click **+ New Resource** -> **Git Repository** (or **Public Repository**).
   - Point to your repository containing this code.
2. **Build Configuration**:
   - Build Pack: **Dockerfile** (or **Docker Compose**).
   - Base Directory: `/`
   - Port: `8000`
3. **Storage / Persistent Volumes (Crucial for SQLite)**:
   - Navigate to the **Storages** tab of your new service in Coolify.
   - Add a persistent volume:
     - **Name**: `flight_tracker_data`
     - **Destination path in container**: `/app/data`
   - *This ensures your historical price logs persist across container updates and restarts.*
4. **Environment Variables**:
   Under the **Environment Variables** tab, add:
   ```env
   PORT=8000
   CHECK_INTERVAL_MINUTES=60
   TRACK_DATE_MODE=today
   RUN_SCRAPE_ON_STARTUP=true
   DEFAULT_CURRENCY=INR

   # Bright Data IP Protection Credentials
   BRIGHT_DATA_API_KEY=your_bright_data_api_key_here
   BRIGHT_DATA_ZONE=serp_api1
   ```
5. **Deploy**:
   - Click **Deploy**.
   - Once deployed, open your assigned Coolify domain to view your live flight tracker dashboard!

---

### Method 2: Deploy with Docker Compose

If using Coolify's Docker Compose source:

```yaml
services:
  flight-tracker:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: flight_tracker
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - flight_tracker_data:/app/data
    environment:
      - HOST=0.0.0.0
      - PORT=8000
      - DATABASE_URL=sqlite+aiosqlite:///app/data/flights.db
      - CHECK_INTERVAL_MINUTES=60
      - RUN_SCRAPE_ON_STARTUP=true
      - TRACK_DATE_MODE=today
      - DEFAULT_CURRENCY=INR
      - BRIGHT_DATA_API_KEY=${BRIGHT_DATA_API_KEY:-}
      - BRIGHT_DATA_ZONE=${BRIGHT_DATA_ZONE:-serp_api1}
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  flight_tracker_data:
    name: flight_tracker_data
```

---

## 🛡️ Bright Data Integration

To protect your IP from rate-limiting or anti-bot blocks on Google Flights:

1. Create a zone in your [Bright Data Dashboard](https://brightdata.com) (e.g. **SERP API** or **Web Unlocker** zone).
2. Grab your API Key from **Account Settings -> API Keys**.
3. Set the following in your `.env` or Coolify environment:
   ```env
   BRIGHT_DATA_API_KEY=bda_xxxxxxxxxxxxxxxxxxxxxxxxxx
   BRIGHT_DATA_ZONE=serp_api1
   ```
4. **Alternative Proxy Mode**: If using Bright Data's SuperProxy or Proxy Manager tunnel:
   ```env
   BRIGHT_DATA_PROXY_URL=http://brd-customer-hl_xxx-zone-serp_api1:password@brd.superproxy.io:22225
   ```

*Note: If neither is set, AeroTrack gracefully defaults to direct scraping and displays an alert in the dashboard.*

---

## 💻 Local Development

### Prerequisites
- Python 3.11+
- Virtualenv

```bash
# 1. Clone or open directory
cd /home/roomtempraturewater/Projects/flight_tracker

# 2. Create virtualenv and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env to add your Bright Data credentials

# 4. Run application
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## 📡 REST API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Web dashboard |
| `GET` | `/health` | Healthcheck endpoint for Docker / Coolify |
| `GET` | `/api/status` | Current scheduler, BrightData, and system metrics |
| `GET` | `/api/routes` | Active predefined routes with latest logged prices |
| `GET` | `/api/history` | Time-series price points for charting (`?days=7&route_code=HYD-PNQ`) |
| `GET` | `/api/stats` | Price min/avg/max and top carrier statistics |
| `GET` | `/api/logs` | Paginated flight price logs (`?limit=20&offset=0`) |
| `POST` | `/api/scrape/trigger` | Manually triggers an immediate background scrape cycle |
| `GET` | `/api/export` | Download full dataset as a CSV spreadsheet |

---

## 🛠️ Project Structure

```
flight_tracker/
├── app/
│   ├── __init__.py
│   ├── config.py           # Pydantic environment configuration
│   ├── database.py         # SQLAlchemy async engine & SQLite volume setup
│   ├── models.py           # FlightLog and ScrapeJobRun database models
│   ├── scraper.py          # fast-flights + BrightData integration + safe parser
│   ├── scheduler.py        # APScheduler hourly task runner
│   ├── api.py              # REST API endpoints & CSV exporter
│   ├── main.py             # FastAPI entrypoint, lifespan, & static routes
│   ├── static/
│   │   ├── css/styles.css  # Dark theme styling and airline badges
│   │   └── js/app.js       # Frontend controller (Chart.js, auto-refresh, modals)
│   └── templates/
│       └── index.html      # Responsive Tailwind CSS dashboard
├── data/                   # Docker persistent storage directory (flights.db)
├── Dockerfile              # Production Python 3.12-slim container
├── docker-compose.yml      # Coolify / local compose specification
├── requirements.txt        # Pinned dependencies
├── .env.example            # Environment variables template
└── README.md               # Documentation & Coolify instructions
```
