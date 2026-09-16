import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from app.config import settings
from app.database import init_db
from app.api import router as api_router
from app.scheduler import scheduler_instance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("flight_tracker.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing flight tracker database...")
    await init_db()

    logger.info("Starting background daily scrape scheduler...")
    scheduler_instance.start()

    if settings.RUN_SCRAPE_ON_STARTUP:
        logger.info("Scheduling initial scrape run on startup...")
        asyncio.create_task(scheduler_instance.run_scrape_cycle())

    yield

    # Shutdown
    logger.info("Stopping scheduler...")
    scheduler_instance.stop()


app = FastAPI(
    title="AeroTrack — Flight Price Intelligence",
    description="Multi-date flight price tracking with per-day scrape scheduling and BrightData IP protection.",
    version="2.0.0",
    lifespan=lifespan
)

# Mount static and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Include API endpoints
app.include_router(api_router)


@app.get("/", response_class=HTMLResponse)
async def serve_trackers(request: Request):
    """Serves the tracker landing page — shows all date trackers, allows add/remove."""
    return templates.TemplateResponse(
        request=request,
        name="trackers.html",
        context={
            "currency": settings.DEFAULT_CURRENCY,
            "max_trackers": settings.MAX_ACTIVE_TRACKERS,
            "max_scrapes_per_day": settings.MAX_SCRAPES_PER_DAY,
            "scrape_times_ist": settings.SCRAPE_TIMES_IST,
        }
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(request: Request, date: str = ""):
    """
    Serves the flight price dashboard for a specific tracked date.
    The ?date=YYYY-MM-DD query param is forwarded to the JS so it can auto-filter.
    """
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "routes": settings.ROUTES,
            "currency": settings.DEFAULT_CURRENCY,
            "has_brightdata": settings.has_bright_data,
            "zone": settings.BRIGHT_DATA_ZONE,
            "flight_date": date,   # passed to template for JS bootstrap
        }
    )


@app.get("/health")
async def health_check():
    """Healthcheck endpoint for Coolify / Docker Compose."""
    return {"status": "ok", "service": "flight_tracker", "version": "2.0.0"}
