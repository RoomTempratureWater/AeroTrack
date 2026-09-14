import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any

from selectolax.lexbor import LexborHTMLParser
from fast_flights import FlightQuery, create_query
from fast_flights.fetcher import fetch_flights_html
from fast_flights.parser import _parse_time
from fast_flights.integrations import BrightData

from app.config import settings

logger = logging.getLogger("flight_tracker.scraper")


class FlightScraper:
    def __init__(self):
        self._bright_data_integration: Optional[BrightData] = None
        self._proxy_url: Optional[str] = None
        self._init_bright_data()

    def _init_bright_data(self):
        """Initialize Bright Data integration if credentials are provided."""
        if settings.BRIGHT_DATA_API_KEY.strip():
            try:
                self._bright_data_integration = BrightData(
                    api_key=settings.BRIGHT_DATA_API_KEY.strip(),
                    zone=settings.BRIGHT_DATA_ZONE.strip(),
                    api_url=settings.BRIGHT_DATA_API_URL.strip() or "https://api.brightdata.com/request"
                )
                logger.info(f"BrightData integration initialized with zone: {settings.BRIGHT_DATA_ZONE}")
            except Exception as e:
                logger.error(f"Failed to initialize BrightData integration: {e}")
                self._bright_data_integration = None
        elif settings.BRIGHT_DATA_PROXY_URL.strip():
            self._proxy_url = settings.BRIGHT_DATA_PROXY_URL.strip()
            logger.info("Using BrightData via HTTP proxy configuration")
        else:
            logger.warning(
                "BrightData is NOT configured. Flight queries will run directly without IP proxy protection. "
                "Set BRIGHT_DATA_API_KEY or BRIGHT_DATA_PROXY_URL in .env to protect your IP."
            )

    @property
    def is_brightdata_active(self) -> bool:
        return self._bright_data_integration is not None or bool(self._proxy_url)

    @property
    def protection_status(self) -> Dict[str, Any]:
        return {
            "active": self.is_brightdata_active,
            "mode": "api" if self._bright_data_integration else ("proxy" if self._proxy_url else "direct"),
            "zone": settings.BRIGHT_DATA_ZONE if self._bright_data_integration else None,
            "configured": settings.has_bright_data
        }

    def _safe_parse_flights_html(self, html: str) -> List[Dict[str, Any]]:
        """
        Safely extracts and parses flight data from Google Flights HTML.
        Resolves upstream bugs where unpriced or sold-out flights raise IndexError.
        """
        parser = LexborHTMLParser(html)
        script = parser.css_first(r"script.ds\:1")
        if not script:
            # Fallback search for any script containing flight data
            for s in parser.css("script"):
                txt = s.text()
                if "data:[" in txt and "HYD" in txt:
                    script = s
                    break
        
        if not script:
            logger.warning("No flight data script found in Google Flights response HTML.")
            return []

        js_content = script.text()
        if "data:" not in js_content:
            return []

        try:
            data = js_content.split("data:", 1)[1].rsplit(",", 1)[0]
            if data.endswith("errorHasStatus: true"):
                logger.warning("Google Flights returned errorHasStatus: true")
                return []
            payload = json.loads(data)
        except Exception as e:
            logger.error(f"Failed to parse JS data payload: {e}")
            return []

        if not isinstance(payload, list) or len(payload) <= 3 or not payload[3]:
            return []

        flights_raw = payload[3][0]
        if not isinstance(flights_raw, list):
            return []

        parsed_flights = []
        for k in flights_raw:
            if not isinstance(k, list) or len(k) == 0:
                continue

            # Safely check price in k[1][0][1]
            price = None
            if len(k) > 1 and isinstance(k[1], list) and len(k[1]) > 0:
                if isinstance(k[1][0], list) and len(k[1][0]) > 1:
                    price = k[1][0][1]

            if price is None or not isinstance(price, int):
                # Skip flights with no confirmed price
                continue

            fl = k[0]
            if not isinstance(fl, list) or len(fl) < 3:
                continue

            airlines_list = fl[1] if len(fl) > 1 and isinstance(fl[1], list) else []
            airline_name = airlines_list[0] if airlines_list else "Unknown Airline"

            legs = fl[2] if isinstance(fl[2], list) else []
            if not legs:
                continue

            first_leg = legs[0]
            last_leg = legs[-1]

            dep_tuple = _parse_time(first_leg[8]) if len(first_leg) > 8 else (0, 0)
            arr_tuple = _parse_time(last_leg[10]) if len(last_leg) > 10 else (0, 0)
            dep_time_str = f"{dep_tuple[0]:02d}:{dep_tuple[1]:02d}"
            arr_time_str = f"{arr_tuple[0]:02d}:{arr_tuple[1]:02d}"

            # Total duration in minutes (first_leg[11] or sum of legs)
            duration_minutes = first_leg[11] if len(first_leg) > 11 and isinstance(first_leg[11], int) else 0
            stops = max(0, len(legs) - 1)
            plane_type = first_leg[17] if len(first_leg) > 17 and isinstance(first_leg[17], str) else None

            # Flight numbers if available
            flight_codes = []
            for leg in legs:
                if len(leg) > 18 and leg[18]:
                    flight_codes.append(str(leg[18]))
            flight_number = ", ".join(flight_codes) if flight_codes else None

            parsed_flights.append({
                "price": price,
                "airline": airline_name,
                "airlines": airlines_list,
                "departure_time": dep_time_str,
                "arrival_time": arr_time_str,
                "duration_minutes": duration_minutes,
                "stops": stops,
                "plane_type": plane_type,
                "flight_number": flight_number,
            })

        return parsed_flights

    def _fetch_route_sync(self, origin: str, destination: str, flight_date: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Synchronous fetch using fast-flights with BrightData or direct connection.
        Returns: (cheapest_flight_dict, all_flights_list)
        """
        query = create_query(
            flights=[
                FlightQuery(
                    date=flight_date,
                    from_airport=origin,
                    to_airport=destination,
                )
            ],
            currency=settings.DEFAULT_CURRENCY,
            trip="one-way",
            seat="economy"
        )

        try:
            html = fetch_flights_html(
                query,
                proxy=self._proxy_url,
                fetch_integration=self._bright_data_integration
            )
            flights = self._safe_parse_flights_html(html)

            if not flights:
                return None, []

            cheapest = min(flights, key=lambda f: f["price"])
            return cheapest, flights

        except Exception as e:
            logger.error(f"Error scraping route {origin}->{destination} on {flight_date}: {e}", exc_info=True)
            return None, []

    async def fetch_route(self, origin: str, destination: str, flight_date: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """Asynchronously executes the synchronous fetch in a thread."""
        return await asyncio.to_thread(self._fetch_route_sync, origin, destination, flight_date)

    def get_target_dates(self) -> List[str]:
        """Calculates which departure date(s) should be queried based on configuration."""
        today = date.today()
        mode = settings.TRACK_DATE_MODE.lower().strip()
        if mode == "tomorrow":
            return [(today + timedelta(days=1)).strftime("%Y-%m-%d")]
        elif mode == "both":
            return [
                today.strftime("%Y-%m-%d"),
                (today + timedelta(days=1)).strftime("%Y-%m-%d")
            ]
        else:
            # Default "today"
            return [today.strftime("%Y-%m-%d")]


scraper_instance = FlightScraper()
