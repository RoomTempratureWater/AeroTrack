from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Date
from app.database import Base


class FlightLog(Base):
    __tablename__ = "flight_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    scrape_timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    
    # Route info
    route_code = Column(String(16), index=True)  # e.g., "HYD-PNQ"
    origin = Column(String(8))                   # e.g., "HYD"
    origin_name = Column(String(64))
    destination = Column(String(8))              # e.g., "PNQ"
    destination_name = Column(String(64))

    # Flight details
    flight_date = Column(String(10), index=True) # "YYYY-MM-DD"
    day_of_week = Column(String(16))             # "Monday"
    price = Column(Integer, index=True)          # Lowest price found in this scrape
    currency = Column(String(8), default="INR")
    airline = Column(String(64))                 # e.g., "IndiGo"
    flight_number = Column(String(32), nullable=True) # e.g., "6E 576"
    departure_time = Column(String(8))           # "16:15"
    arrival_time = Column(String(8))             # "17:55"
    duration_minutes = Column(Integer)           # e.g. 100
    stops = Column(Integer, default=0)
    plane_type = Column(String(64), nullable=True)
    
    # Context
    total_options_found = Column(Integer, default=0)
    is_brightdata_used = Column(Boolean, default=False)
    all_flights_json = Column(Text, nullable=True)


class ScrapeJobRun(Base):
    __tablename__ = "scrape_job_runs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(16), default="running")  # running, success, failed
    routes_checked = Column(Integer, default=0)
    records_logged = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)


class TrackedDate(Base):
    """A user-configured flight date to track prices for (max 5 active at a time)."""
    __tablename__ = "tracked_dates"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # The flight departure date being tracked, e.g. "2026-10-06"
    flight_date = Column(String(10), unique=True, index=True, nullable=False)

    # Human label, e.g. "Diwali trip"
    label = Column(String(128), nullable=True)

    # Whether this tracker is currently active (scraping)
    is_active = Column(Boolean, default=True, index=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    deactivated_at = Column(DateTime, nullable=True)

    # Scrape counters (reset daily at midnight UTC)
    scrapes_today = Column(Integer, default=0)
    last_scrape_date = Column(String(10), nullable=True)  # "YYYY-MM-DD" of last reset
    last_scrape_at = Column(DateTime, nullable=True)

