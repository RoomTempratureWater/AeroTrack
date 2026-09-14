import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import FlightLog, ScrapeJobRun
from app.scraper import scraper_instance

logger = logging.getLogger("flight_tracker.scheduler")


class ScraperScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_scraping: bool = False
        self.last_run_time: Optional[datetime] = None
        self.last_run_status: Optional[str] = None
        self.last_run_summary: Optional[Dict[str, Any]] = None

    def start(self):
        """Starts the scheduler with interval trigger."""
        if not self.scheduler.running:
            self.scheduler.add_job(
                self.run_hourly_scrape,
                trigger=IntervalTrigger(minutes=settings.CHECK_INTERVAL_MINUTES),
                id="flight_scrape_hourly",
                name="Hourly Flight Price Scraper",
                replace_existing=True,
                max_instances=1,
            )
            self.scheduler.start()
            logger.info(f"Scheduler started. Job scheduled every {settings.CHECK_INTERVAL_MINUTES} minutes.")

    def stop(self):
        """Stops the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")

    @property
    def next_run_time(self) -> Optional[datetime]:
        job = self.scheduler.get_job("flight_scrape_hourly")
        if job and job.next_run_time:
            return job.next_run_time
        return None

    async def run_hourly_scrape(self) -> Dict[str, Any]:
        """
        Executes a scrape cycle for all configured routes and dates.
        Logs the cheapest flight of that day to the database.
        """
        if self.is_scraping:
            logger.warning("Scrape cycle already in progress, skipping concurrent run.")
            return {"status": "skipped", "reason": "already_running"}

        self.is_scraping = True
        start_time = datetime.now(timezone.utc)
        logger.info(f"Starting flight price scrape cycle at {start_time.isoformat()}")

        routes_checked = 0
        records_logged = 0
        error_msg: Optional[str] = None

        job_run = ScrapeJobRun(
            started_at=start_time,
            status="running",
            routes_checked=0,
            records_logged=0
        )

        async with async_session() as session:
            session.add(job_run)
            await session.commit()
            await session.refresh(job_run)
            job_run_id = job_run.id

        target_dates = scraper_instance.get_target_dates()

        try:
            for route in settings.ROUTES:
                origin = route["origin"]
                dest = route["destination"]
                route_code = route["code"]

                for flight_date in target_dates:
                    routes_checked += 1
                    logger.info(f"Checking {route_code} ({route['origin_name']} -> {route['destination_name']}) for date {flight_date}")

                    cheapest, all_flights = await scraper_instance.fetch_route(origin, dest, flight_date)

                    # If no flights found for today (e.g., late evening), try checking tomorrow
                    if not cheapest and flight_date == datetime.now().strftime("%Y-%m-%d"):
                        tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                        if tomorrow_str not in target_dates:
                            logger.info(f"No flights left today for {route_code}. Trying tomorrow: {tomorrow_str}")
                            cheapest, all_flights = await scraper_instance.fetch_route(origin, dest, tomorrow_str)
                            if cheapest:
                                flight_date = tomorrow_str

                    if cheapest:
                        day_name = datetime.strptime(flight_date, "%Y-%m-%d").strftime("%A")
                        
                        log_entry = FlightLog(
                            scrape_timestamp=datetime.now(timezone.utc),
                            route_code=route_code,
                            origin=origin,
                            origin_name=route["origin_name"],
                            destination=dest,
                            destination_name=route["destination_name"],
                            flight_date=flight_date,
                            day_of_week=day_name,
                            price=cheapest["price"],
                            currency=settings.DEFAULT_CURRENCY,
                            airline=cheapest["airline"],
                            flight_number=cheapest.get("flight_number"),
                            departure_time=cheapest["departure_time"],
                            arrival_time=cheapest["arrival_time"],
                            duration_minutes=cheapest["duration_minutes"],
                            stops=cheapest["stops"],
                            plane_type=cheapest.get("plane_type"),
                            total_options_found=len(all_flights),
                            is_brightdata_used=scraper_instance.is_brightdata_active,
                            all_flights_json=json.dumps(all_flights)
                        )

                        async with async_session() as session:
                            session.add(log_entry)
                            await session.commit()

                        records_logged += 1
                        logger.info(
                            f"Logged cheapest for {route_code} on {flight_date}: ₹{cheapest['price']} "
                            f"({cheapest['airline']}) dep {cheapest['departure_time']} arr {cheapest['arrival_time']}"
                        )
                    else:
                        logger.warning(f"No valid flight prices retrieved for {route_code} on {flight_date}")

                    # Polite 1.5 second pause between route queries
                    await asyncio.sleep(1.5)

            status = "success"
        except Exception as e:
            logger.error(f"Error during scrape cycle: {e}", exc_info=True)
            status = "failed"
            error_msg = str(e)
        finally:
            self.is_scraping = False
            finish_time = datetime.now(timezone.utc)
            self.last_run_time = finish_time
            self.last_run_status = status

            summary = {
                "status": status,
                "started_at": start_time.isoformat(),
                "finished_at": finish_time.isoformat(),
                "duration_seconds": (finish_time - start_time).total_seconds(),
                "routes_checked": routes_checked,
                "records_logged": records_logged,
                "error": error_msg
            }
            self.last_run_summary = summary

            # Update job run record
            try:
                async with async_session() as session:
                    result = await session.execute(
                        select(ScrapeJobRun).where(ScrapeJobRun.id == job_run_id)
                    )
                    record = result.scalar_one_or_none()
                    if record:
                        record.finished_at = finish_time
                        record.status = status
                        record.routes_checked = routes_checked
                        record.records_logged = records_logged
                        record.error_message = error_msg
                        await session.commit()
            except Exception as e:
                logger.error(f"Failed to update ScrapeJobRun in DB: {e}")

        logger.info(f"Scrape cycle finished with status={status}. Logged {records_logged} records.")
        return summary


scheduler_instance = ScraperScheduler()
