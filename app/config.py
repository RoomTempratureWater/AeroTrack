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
    CHECK_INTERVAL_MINUTES: int = 60
    RUN_SCRAPE_ON_STARTUP: bool = True
    TRACK_DATE_MODE: str = "today"  # today, tomorrow, both
    DEFAULT_CURRENCY: str = "INR"

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


settings = Settings()
