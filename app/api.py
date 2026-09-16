import io
import csv
import json
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import FlightLog, ScrapeJobRun, TrackedDate
from app.scraper import scraper_instance
from app.scheduler import scheduler_instance

router = APIRouter(prefix="/api", tags=["flights"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────

class TrackerCreate(BaseModel):
    flight_date: str       # "YYYY-MM-DD"
    label: Optional[str] = None

    @field_validator("flight_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            parsed = datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("flight_date must be YYYY-MM-DD format")
        if parsed <= date.today():
            raise ValueError("flight_date must be a future date")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# Tracker CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/trackers")
async def get_trackers(db: AsyncSession = Depends(get_db)):
    """
    Returns all tracked dates (active and inactive), ordered by flight date.
    Includes a summary of the latest and lowest price found per tracker.
    """
    res = await db.execute(
        select(TrackedDate).order_by(TrackedDate.flight_date.asc())
    )
    trackers = res.scalars().all()

    output = []
    for t in trackers:
        # Latest log entry across all routes for this date
        latest_res = await db.execute(
            select(FlightLog)
            .where(FlightLog.flight_date == t.flight_date)
            .order_by(desc(FlightLog.scrape_timestamp))
            .limit(1)
        )
        latest = latest_res.scalar_one_or_none()

        # Lowest ever price across all routes for this date
        min_res = await db.execute(
            select(func.min(FlightLog.price))
            .where(FlightLog.flight_date == t.flight_date)
        )
        lowest_price = min_res.scalar_one_or_none()

        # Count total records for this date
        count_res = await db.execute(
            select(func.count(FlightLog.id))
            .where(FlightLog.flight_date == t.flight_date)
        )
        total_records = count_res.scalar_one()

        output.append({
            "id": t.id,
            "flight_date": t.flight_date,
            "label": t.label,
            "is_active": t.is_active,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "deactivated_at": t.deactivated_at.isoformat() if t.deactivated_at else None,
            "scrapes_today": t.scrapes_today or 0,
            "max_scrapes_per_day": settings.MAX_SCRAPES_PER_DAY,
            "last_scrape_at": t.last_scrape_at.isoformat() if t.last_scrape_at else None,
            "total_records": total_records,
            "lowest_price": lowest_price,
            "latest_price": latest.price if latest else None,
            "latest_airline": latest.airline if latest else None,
            "latest_scrape_at": latest.scrape_timestamp.isoformat() if latest else None,
        })

    return output


@router.post("/trackers", status_code=201)
async def create_tracker(payload: TrackerCreate, db: AsyncSession = Depends(get_db)):
    """
    Creates a new date tracker.
    Enforces a cap of MAX_ACTIVE_TRACKERS simultaneously active trackers.
    Returns 409 if the date is already tracked, or if the active cap is reached.
    """
    # Check active cap
    active_count_res = await db.execute(
        select(func.count(TrackedDate.id)).where(TrackedDate.is_active == True)
    )
    active_count = active_count_res.scalar_one()
    if active_count >= settings.MAX_ACTIVE_TRACKERS:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Maximum of {settings.MAX_ACTIVE_TRACKERS} active trackers reached. "
                "Please deactivate or delete an existing tracker first."
            )
        )

    # Check for duplicate date (active or inactive)
    existing_res = await db.execute(
        select(TrackedDate).where(TrackedDate.flight_date == payload.flight_date)
    )
    existing = existing_res.scalar_one_or_none()

    if existing:
        if existing.is_active:
            raise HTTPException(
                status_code=409,
                detail=f"A tracker for {payload.flight_date} already exists and is active."
            )
        # Re-activate an old deactivated tracker for the same date
        existing.is_active = True
        existing.label = payload.label or existing.label
        existing.deactivated_at = None
        existing.scrapes_today = 0
        existing.last_scrape_date = None
        await db.commit()
        await db.refresh(existing)
        return {"id": existing.id, "flight_date": existing.flight_date, "status": "reactivated"}

    tracker = TrackedDate(
        flight_date=payload.flight_date,
        label=payload.label,
    )
    db.add(tracker)
    await db.commit()
    await db.refresh(tracker)
    return {"id": tracker.id, "flight_date": tracker.flight_date, "status": "created"}


@router.delete("/trackers/{tracker_id}", status_code=200)
async def delete_tracker(tracker_id: int, db: AsyncSession = Depends(get_db)):
    """
    Permanently deletes a tracker (and its metadata).
    Historical FlightLog records for that date are preserved.
    """
    res = await db.execute(select(TrackedDate).where(TrackedDate.id == tracker_id))
    tracker = res.scalar_one_or_none()
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found.")
    await db.delete(tracker)
    await db.commit()
    return {"status": "deleted", "id": tracker_id}


@router.patch("/trackers/{tracker_id}/deactivate", status_code=200)
async def deactivate_tracker(tracker_id: int, db: AsyncSession = Depends(get_db)):
    """Deactivates a tracker (stops scraping) without deleting it or its history."""
    res = await db.execute(select(TrackedDate).where(TrackedDate.id == tracker_id))
    tracker = res.scalar_one_or_none()
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found.")
    tracker.is_active = False
    tracker.deactivated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "deactivated", "id": tracker_id}


@router.patch("/trackers/{tracker_id}/activate", status_code=200)
async def activate_tracker(tracker_id: int, db: AsyncSession = Depends(get_db)):
    """Re-activates a previously deactivated tracker (subject to cap check)."""
    active_count_res = await db.execute(
        select(func.count(TrackedDate.id)).where(TrackedDate.is_active == True)
    )
    active_count = active_count_res.scalar_one()
    if active_count >= settings.MAX_ACTIVE_TRACKERS:
        raise HTTPException(
            status_code=409,
            detail=f"Maximum of {settings.MAX_ACTIVE_TRACKERS} active trackers reached."
        )

    res = await db.execute(select(TrackedDate).where(TrackedDate.id == tracker_id))
    tracker = res.scalar_one_or_none()
    if not tracker:
        raise HTTPException(status_code=404, detail="Tracker not found.")
    tracker.is_active = True
    tracker.deactivated_at = None
    await db.commit()
    return {"status": "activated", "id": tracker_id}


# ─────────────────────────────────────────────────────────────────────────────
# System status
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_system_status(db: AsyncSession = Depends(get_db)):
    """Returns current scheduler status, BrightData connection status, and database metrics."""
    total_logs_result = await db.execute(select(func.count(FlightLog.id)))
    total_logs = total_logs_result.scalar_one()

    # Get last job run
    last_run_result = await db.execute(
        select(ScrapeJobRun).order_by(desc(ScrapeJobRun.started_at)).limit(1)
    )
    last_run = last_run_result.scalar_one_or_none()

    # Active tracker count
    active_trackers_res = await db.execute(
        select(func.count(TrackedDate.id)).where(TrackedDate.is_active == True)
    )
    active_trackers_count = active_trackers_res.scalar_one()

    next_run = scheduler_instance.next_run_time
    next_run_iso = next_run.isoformat() if next_run else None

    return {
        "status": "healthy",
        "is_scraping": scheduler_instance.is_scraping,
        "next_run_at": next_run_iso,
        "scrape_times_ist": scheduler_instance.scheduled_times_ist,
        "max_scrapes_per_day": settings.MAX_SCRAPES_PER_DAY,
        "brightdata": scraper_instance.protection_status,
        "total_records": total_logs,
        "routes_count": len(settings.ROUTES),
        "active_trackers": active_trackers_count,
        "max_active_trackers": settings.MAX_ACTIVE_TRACKERS,
        "last_job_run": {
            "started_at": last_run.started_at.isoformat() if last_run else None,
            "finished_at": last_run.finished_at.isoformat() if (last_run and last_run.finished_at) else None,
            "status": last_run.status if last_run else None,
            "records_logged": last_run.records_logged if last_run else 0,
            "error_message": last_run.error_message if last_run else None,
        } if last_run else None
    }


# ─────────────────────────────────────────────────────────────────────────────
# Routes / History / Stats / Logs — with optional flight_date filter
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/routes")
async def get_routes(
    flight_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Returns all predefined routes with their latest logged price and flight details.
    Optionally filter by a specific flight_date (YYYY-MM-DD) to show per-tracker data.
    """
    routes_summary = []

    for route in settings.ROUTES:
        code = route["code"]

        # Base query, optionally filtered by flight_date
        base_filter = [FlightLog.route_code == code]
        if flight_date:
            base_filter.append(FlightLog.flight_date == flight_date)

        # Fetch latest 2 logs for this route (+ optional date filter)
        latest_res = await db.execute(
            select(FlightLog)
            .where(*base_filter)
            .order_by(desc(FlightLog.scrape_timestamp))
            .limit(2)
        )
        logs = latest_res.scalars().all()
        latest = logs[0] if logs else None
        previous = logs[1] if len(logs) > 1 else None

        price_diff = None
        if latest and previous and previous.price:
            price_diff = latest.price - previous.price

        # Lowest ever price (scoped to date if provided)
        min_res = await db.execute(
            select(func.min(FlightLog.price)).where(*base_filter)
        )
        lowest_price = min_res.scalar_one_or_none()

        routes_summary.append({
            "code": code,
            "origin": route["origin"],
            "origin_name": route["origin_name"],
            "destination": route["destination"],
            "destination_name": route["destination_name"],
            "latest": {
                "id": latest.id,
                "price": latest.price,
                "currency": latest.currency,
                "airline": latest.airline,
                "flight_number": latest.flight_number,
                "flight_date": latest.flight_date,
                "day_of_week": latest.day_of_week,
                "departure_time": latest.departure_time,
                "arrival_time": latest.arrival_time,
                "duration_minutes": latest.duration_minutes,
                "stops": latest.stops,
                "scrape_timestamp": latest.scrape_timestamp.isoformat(),
                "is_brightdata_used": latest.is_brightdata_used,
            } if latest else None,
            "price_diff_vs_previous": price_diff,
            "lowest_ever_price": lowest_price
        })

    return routes_summary


@router.get("/history")
async def get_price_history(
    route_code: Optional[str] = None,
    flight_date: Optional[str] = None,
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns time-series flight price points for charting.
    Can be filtered by route_code and/or a specific flight_date.
    """
    since_time = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = select(FlightLog).where(FlightLog.scrape_timestamp >= since_time)

    if route_code:
        stmt = stmt.where(FlightLog.route_code == route_code)
    if flight_date:
        stmt = stmt.where(FlightLog.flight_date == flight_date)

    stmt = stmt.order_by(FlightLog.scrape_timestamp.asc())
    result = await db.execute(stmt)
    records = result.scalars().all()

    # Structure data by route
    routes_data: Dict[str, List[Dict[str, Any]]] = {}
    for r in settings.ROUTES:
        routes_data[r["code"]] = []

    for item in records:
        if item.route_code not in routes_data:
            routes_data[item.route_code] = []

        routes_data[item.route_code].append({
            "timestamp": item.scrape_timestamp.isoformat(),
            "price": item.price,
            "airline": item.airline,
            "flight_date": item.flight_date,
            "departure_time": item.departure_time,
            "arrival_time": item.arrival_time,
            "stops": item.stops,
            "flight_number": item.flight_number,
        })

    return {
        "days": days,
        "flight_date": flight_date,
        "routes": routes_data
    }


@router.get("/stats")
async def get_flight_stats(
    flight_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Computes overall statistics: minimum, average, and maximum prices per route.
    Optionally scoped to a specific flight_date.
    """
    stats = []

    for route in settings.ROUTES:
        code = route["code"]

        base_filter = [FlightLog.route_code == code]
        if flight_date:
            base_filter.append(FlightLog.flight_date == flight_date)

        res = await db.execute(
            select(
                func.min(FlightLog.price),
                func.avg(FlightLog.price),
                func.max(FlightLog.price),
                func.count(FlightLog.id)
            ).where(*base_filter)
        )
        min_p, avg_p, max_p, count_p = res.one()

        # Find most frequent cheapest airline
        airline_res = await db.execute(
            select(FlightLog.airline, func.count(FlightLog.id))
            .where(*base_filter)
            .group_by(FlightLog.airline)
            .order_by(desc(func.count(FlightLog.id)))
            .limit(1)
        )
        top_airline_row = airline_res.first()
        top_airline = top_airline_row[0] if top_airline_row else "N/A"

        stats.append({
            "route_code": code,
            "origin_name": route["origin_name"],
            "destination_name": route["destination_name"],
            "total_checks": count_p,
            "min_price": min_p,
            "avg_price": round(avg_p, 2) if avg_p else None,
            "max_price": max_p,
            "most_common_airline": top_airline
        })

    return stats


@router.get("/logs")
async def get_flight_logs(
    route_code: Optional[str] = None,
    flight_date: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """Returns paginated flight price logs with complete details."""
    query = select(FlightLog)
    count_query = select(func.count(FlightLog.id))

    if route_code:
        query = query.where(FlightLog.route_code == route_code)
        count_query = count_query.where(FlightLog.route_code == route_code)
    if flight_date:
        query = query.where(FlightLog.flight_date == flight_date)
        count_query = count_query.where(FlightLog.flight_date == flight_date)

    total_count_res = await db.execute(count_query)
    total_count = total_count_res.scalar_one()

    query = query.order_by(desc(FlightLog.scrape_timestamp)).limit(limit).offset(offset)
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": item.id,
                "scrape_timestamp": item.scrape_timestamp.isoformat(),
                "route_code": item.route_code,
                "origin": item.origin,
                "origin_name": item.origin_name,
                "destination": item.destination,
                "destination_name": item.destination_name,
                "flight_date": item.flight_date,
                "day_of_week": item.day_of_week,
                "price": item.price,
                "currency": item.currency,
                "airline": item.airline,
                "flight_number": item.flight_number,
                "departure_time": item.departure_time,
                "arrival_time": item.arrival_time,
                "duration_minutes": item.duration_minutes,
                "stops": item.stops,
                "plane_type": item.plane_type,
                "total_options_found": item.total_options_found,
                "is_brightdata_used": item.is_brightdata_used,
                "all_flights": json.loads(item.all_flights_json) if item.all_flights_json else []
            }
            for item in items
        ]
    }


@router.post("/scrape/trigger")
async def trigger_manual_scrape(background_tasks: BackgroundTasks):
    """Triggers an immediate scrape cycle in the background."""
    if scheduler_instance.is_scraping:
        return {"status": "in_progress", "message": "A scrape cycle is already running."}

    background_tasks.add_task(scheduler_instance.run_scrape_cycle)
    return {
        "status": "triggered",
        "message": "Scrape cycle started in background.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/export")
async def export_logs_csv(
    flight_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Exports all (or date-filtered) logged flight prices as a downloadable CSV."""
    stmt = select(FlightLog).order_by(desc(FlightLog.scrape_timestamp))
    if flight_date:
        stmt = stmt.where(FlightLog.flight_date == flight_date)
    res = await db.execute(stmt)
    records = res.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Scrape Timestamp (UTC)", "Route", "Origin", "Destination",
        "Flight Date", "Day of Week", "Price (INR)", "Airline", "Flight Number",
        "Departure Time", "Arrival Time", "Duration (mins)", "Stops", "Plane Type",
        "BrightData Protected"
    ])

    for r in records:
        writer.writerow([
            r.id,
            r.scrape_timestamp.isoformat() if r.scrape_timestamp else "",
            r.route_code,
            r.origin,
            r.destination,
            r.flight_date,
            r.day_of_week,
            r.price,
            r.airline,
            r.flight_number or "",
            r.departure_time,
            r.arrival_time,
            r.duration_minutes,
            r.stops,
            r.plane_type or "",
            "Yes" if r.is_brightdata_used else "No"
        ])

    output.seek(0)
    suffix = f"_{flight_date}" if flight_date else ""
    filename = f"flight_prices{suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
