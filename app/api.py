import io
import csv
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import FlightLog, ScrapeJobRun
from app.scraper import scraper_instance
from app.scheduler import scheduler_instance

router = APIRouter(prefix="/api", tags=["flights"])


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

    next_run = scheduler_instance.next_run_time
    next_run_iso = next_run.isoformat() if next_run else None

    return {
        "status": "healthy",
        "is_scraping": scheduler_instance.is_scraping,
        "next_run_at": next_run_iso,
        "check_interval_minutes": settings.CHECK_INTERVAL_MINUTES,
        "brightdata": scraper_instance.protection_status,
        "total_records": total_logs,
        "routes_count": len(settings.ROUTES),
        "track_date_mode": settings.TRACK_DATE_MODE,
        "last_job_run": {
            "started_at": last_run.started_at.isoformat() if last_run else None,
            "finished_at": last_run.finished_at.isoformat() if (last_run and last_run.finished_at) else None,
            "status": last_run.status if last_run else None,
            "records_logged": last_run.records_logged if last_run else 0,
            "error_message": last_run.error_message if last_run else None,
        } if last_run else None
    }


@router.get("/routes")
async def get_routes(db: AsyncSession = Depends(get_db)):
    """Returns all predefined routes along with their latest logged price and flight details."""
    routes_summary = []

    for route in settings.ROUTES:
        code = route["code"]

        # Fetch latest logged flight for this route
        latest_res = await db.execute(
            select(FlightLog)
            .where(FlightLog.route_code == code)
            .order_by(desc(FlightLog.scrape_timestamp))
            .limit(2)
        )
        logs = latest_res.scalars().all()
        latest = logs[0] if logs else None
        previous = logs[1] if len(logs) > 1 else None

        price_diff = None
        if latest and previous and previous.price:
            price_diff = latest.price - previous.price

        # Fetch lowest ever price
        min_res = await db.execute(
            select(func.min(FlightLog.price)).where(FlightLog.route_code == code)
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
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns time-series flight price points for charting.
    Can be filtered by route_code or returns all routes grouped.
    """
    since_time = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = select(FlightLog).where(FlightLog.scrape_timestamp >= since_time)

    if route_code:
        stmt = stmt.where(FlightLog.route_code == route_code)

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
        "routes": routes_data
    }


@router.get("/stats")
async def get_flight_stats(db: AsyncSession = Depends(get_db)):
    """Computes overall statistics: minimum, average, and maximum prices per route."""
    stats = []

    for route in settings.ROUTES:
        code = route["code"]
        res = await db.execute(
            select(
                func.min(FlightLog.price),
                func.avg(FlightLog.price),
                func.max(FlightLog.price),
                func.count(FlightLog.id)
            ).where(FlightLog.route_code == code)
        )
        min_p, avg_p, max_p, count_p = res.one()

        # Find most frequent cheapest airline
        airline_res = await db.execute(
            select(FlightLog.airline, func.count(FlightLog.id))
            .where(FlightLog.route_code == code)
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

    background_tasks.add_task(scheduler_instance.run_hourly_scrape)
    return {
        "status": "triggered",
        "message": "Scrape cycle started in background.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/export")
async def export_logs_csv(db: AsyncSession = Depends(get_db)):
    """Exports all logged flight prices as a downloadable CSV."""
    stmt = select(FlightLog).order_by(desc(FlightLog.scrape_timestamp))
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
    filename = f"flight_prices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
