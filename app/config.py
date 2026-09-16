import os
from typing import List, Dict
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///data/flights.db"

    # Scheduler & Tracking
    # CHECK_INTERVAL_MINUTES is kept for backward compat but superseded by SCRAPE_TIMES_IST
    CHECK_INTERVAL_MINUTES: int = 60
    RUN_SCRAPE_ON_STARTUP: bool = True
    DEFAULT_CURRENCY: str = "INR"

    # Multi-date tracker settings
    MAX_ACTIVE_TRACKERS: int = 5          # Max simultaneous active date trackers
    MAX_SCRAPES_PER_DAY: int = 3          # How many times per day each tracker runs
    # Comma-separated HH:MM times in IST (UTC+5:30) when all active trackers are scraped
    SCRAPE_TIMES_IST: str = "08:00,13:00,20:00"

    # Bright Data Integration
    BRIGHT_DATA_API_KEY: str = ""
    BRIGHT_DATA_ZONE: str = "serp_api1"
    BRIGHT_DATA_API_URL: str = "https://api.brightdata.com/request"
    BRIGHT_DATA_PROXY_URL: str = ""

    # Predefined Routes
    ROUTES: List[Dict[str, str]] = [
        {
            "code": "HYD-PNQ",
            "origin": "HYD",
            "origin_name": "Hyderabad (HYD)",
            "destination": "PNQ",
            "destination_name": "Pune (PNQ)"
        },
        {
            "code": "PNQ-HYD",
            "origin": "PNQ",
            "origin_name": "Pune (PNQ)",
            "destination": "HYD",
            "destination_name": "Hyderabad (HYD)"
        },
        {
            "code": "BOM-HYD",
            "origin": "BOM",
            "origin_name": "Mumbai (BOM)",
            "destination": "HYD",
            "destination_name": "Hyderabad (HYD)"
        },
        {
            "code": "HYD-BOM",
            "origin": "HYD",
            "origin_name": "Hyderabad (HYD)",
            "destination": "BOM",
            "destination_name": "Mumbai (BOM)"
        }
    ]

    @property
    def has_bright_data(self) -> bool:
        return bool(self.BRIGHT_DATA_API_KEY.strip() or self.BRIGHT_DATA_PROXY_URL.strip())

    @property
    def scrape_times_utc(self) -> list:
        """Parse SCRAPE_TIMES_IST into (hour, minute) UTC tuples. IST = UTC+5:30."""
        result = []
        for t in self.SCRAPE_TIMES_IST.split(","):
            t = t.strip()
            try:
                h, m = map(int, t.split(":"))
                # Convert IST → UTC: subtract 5h30m
                total_minutes = h * 60 + m - 330
                # Wrap around midnight
                total_minutes %= 1440
                result.append((total_minutes // 60, total_minutes % 60))
            except (ValueError, AttributeError):
                pass
        return result


settings = Settings()
