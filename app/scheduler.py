import asyncio
import json
import logging
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import FlightLog, ScrapeJobRun, TrackedDate
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
        """Starts the scheduler with 3 fixed daily cron jobs derived from SCRAPE_TIMES_IST."""
        if self.scheduler.running:
            return

        scrape_times = settings.scrape_times_utc
        if not scrape_times:
            # Fallback: every CHECK_INTERVAL_MINUTES
            logger.warning("No valid SCRAPE_TIMES_IST parsed. Falling back to interval trigger.")
            from apscheduler.triggers.interval import IntervalTrigger
            self.scheduler.add_job(
                self.run_scrape_cycle,
                trigger=IntervalTrigger(minutes=settings.CHECK_INTERVAL_MINUTES),
                id="flight_scrape_fallback",
                name="Flight Price Scraper (fallback interval)",
                replace_existing=True,
                max_instances=1,
            )
        else:
            for i, (hour, minute) in enumerate(scrape_times):
                job_id = f"flight_scrape_{i}"
                self.scheduler.add_job(
                    self.run_scrape_cycle,
                    trigger=CronTrigger(hour=hour, minute=minute, timezone="UTC"),
                    id=job_id,
                    name=f"Daily Flight Scrape #{i+1} ({hour:02d}:{minute:02d} UTC)",
                    replace_existing=True,
                    max_instances=1,
                )
                logger.info(f"Scheduled scrape job #{i+1} at {hour:02d}:{minute:02d} UTC")

        self.scheduler.start()
        logger.info(f"Scheduler started with {len(scrape_times)} daily scrape time(s).")

    def stop(self):
        """Stops the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")

    @property
    def next_run_time(self) -> Optional[datetime]:
        """Returns the nearest upcoming run across all scheduled jobs."""
        earliest = None
        for job in self.scheduler.get_jobs():
            if job.next_run_time:
                if earliest is None or job.next_run_time < earliest:
                    earliest = job.next_run_time
        return earliest

    @property
    def scheduled_times_ist(self) -> List[str]:
        """Human-readable list of scrape times in IST for the UI."""
        times = []
        for h, m in settings.scrape_times_utc:
            # UTC → IST: add 5h30m
            total = h * 60 + m + 330
            total %= 1440
            times.append(f"{total // 60:02d}:{total % 60:02d} IST")
        return times

    async def _get_active_tracked_dates(self) -> List[TrackedDate]:
        """
        Fetches all active TrackedDate records from the DB.
        Auto-deactivates any dates that are in the past.
        Also resets the per-day scrape counter when the UTC date has rolled over.
        """
        today_str = date.today().isoformat()
        results = []

        async with async_session() as session:
            res = await session.execute(
                select(TrackedDate).where(TrackedDate.is_active == True)
            )
            trackers = res.scalars().all()

            for tracker in trackers:
                # Deactivate past dates
                if tracker.flight_date < today_str:
                    tracker.is_active = False
                    tracker.deactivated_at = datetime.now(timezone.utc)
                    logger.info(
                        f"Auto-deactivated past tracker: {tracker.flight_date} "
                        f"(id={tracker.id})"
                    )
                    await session.commit()
                    continue

                # Reset per-day counter if it's a new calendar day (UTC)
                if tracker.last_scrape_date != today_str:
                    tracker.scrapes_today = 0
                    tracker.last_scrape_date = today_str
                    await session.commit()

                results.append(tracker)

        return results

    async def run_scrape_cycle(self) -> Dict[str, Any]:
        """
        Executes one scrape cycle for all active tracked dates × all routes.
        Skips a tracked date if it has already been scraped MAX_SCRAPES_PER_DAY times today.
        Logs the cheapest flight found per route-date pair to the database.
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

        # Fetch active tracked dates (with auto-deactivation of past dates)
        active_trackers = await self._get_active_tracked_dates()

        if not active_trackers:
            logger.info("No active date trackers configured. Skipping scrape cycle.")
            status = "success"
            self.is_scraping = False
            summary = {
                "status": status,
                "started_at": start_time.isoformat(),
                "finished_at": start_time.isoformat(),
                "duration_seconds": 0,
                "routes_checked": 0,
                "records_logged": 0,
                "error": None,
                "skipped_trackers": "no active trackers"
            }
            self.last_run_summary = summary
            return summary

        try:
            for tracker in active_trackers:
                flight_date = tracker.flight_date
                today_str = date.today().isoformat()

                # Enforce per-day scrape cap
                if tracker.last_scrape_date == today_str and tracker.scrapes_today >= settings.MAX_SCRAPES_PER_DAY:
                    logger.info(
                        f"Tracker {flight_date} already scraped "
                        f"{tracker.scrapes_today}/{settings.MAX_SCRAPES_PER_DAY} times today. Skipping."
                    )
                    continue

                logger.info(
                    f"Scraping tracker {flight_date} "
                    f"(scrape {tracker.scrapes_today + 1}/{settings.MAX_SCRAPES_PER_DAY} today)"
                )

                for route in settings.ROUTES:
                    origin = route["origin"]
                    dest = route["destination"]
                    route_code = route["code"]
                    routes_checked += 1

                    logger.info(
                        f"  Checking {route_code} "
                        f"({route['origin_name']} → {route['destination_name']}) "
                        f"for {flight_date}"
                    )

                    cheapest, all_flights = await scraper_instance.fetch_route(origin, dest, flight_date)

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
                            f"  Logged: ₹{cheapest['price']} via {cheapest['airline']} "
                            f"dep {cheapest['departure_time']} arr {cheapest['arrival_time']}"
                        )
                    else:
                        logger.warning(
                            f"  No valid prices for {route_code} on {flight_date}"
                        )

                    # Polite pause between route queries
                    await asyncio.sleep(1.5)

                # Update scrape counter on the tracker
                async with async_session() as session:
                    res = await session.execute(
                        select(TrackedDate).where(TrackedDate.id == tracker.id)
                    )
                    t = res.scalar_one_or_none()
                    if t:
                        t.scrapes_today = (t.scrapes_today or 0) + 1
                        t.last_scrape_at = datetime.now(timezone.utc)
                        t.last_scrape_date = today_str
                        await session.commit()

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

        logger.info(
            f"Scrape cycle finished: status={status}, "
            f"{records_logged} records logged across {routes_checked} route checks."
        )
        return summary

    # Keep old method name as alias so existing callers (startup trigger) still work
    async def run_hourly_scrape(self) -> Dict[str, Any]:
        return await self.run_scrape_cycle()


scheduler_instance = ScraperScheduler()
