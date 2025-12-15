import requests
import math
from .utils import TTLCache

def _round_coord(x, decimals=5):
    # Helps caching by grouping nearby points
    return round(x, decimals)

class OSMMaxSpeedClient:
    def __init__(self, overpass_url: str, radius_m: int, cache_seconds: int, logger):
        self.url = overpass_url
        self.radius = radius_m
        self.cache = TTLCache(cache_seconds)
        self.logger = logger

    def _build_query(self, lat: float, lon: float):
        # Finds ways within radius and returns tags (including maxspeed)
        # Note: Overpass QL
        return f"""
        [out:json][timeout:10];
        (
          way(around:{self.radius},{lat},{lon})["highway"];
        );
        out tags center 1;
        """

    def get_maxspeed_mph(self, lat: float, lon: float):
        key = (_round_coord(lat), _round_coord(lon), self.radius)
        cached = self.cache.get(key)
        if cached is not None:
            return cached  # may be int or None

        query = self._build_query(lat, lon)
        try:
            r = requests.post(self.url, data={"data": query}, timeout=12)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            self.logger.warning(f"Overpass query failed: {e}")
            self.cache.set(key, None)
            return None

        elements = data.get("elements", [])
        # Pick first with maxspeed if any; otherwise None
        for el in elements:
            tags = el.get("tags", {})
            ms = tags.get("maxspeed")
            if not ms:
                continue

            mph = self._parse_maxspeed_to_mph(ms)
            if mph is not None:
                self.cache.set(key, mph)
                return mph

        self.cache.set(key, None)
        return None

    def _parse_maxspeed_to_mph(self, ms: str):
        """
        Handles:
          "30" (often km/h outside UK, but UK OSM uses mph by default in many places)
          "30 mph"
          "50 km/h"
          "national", "signals", etc -> None
        """
        ms = ms.strip().lower()

        # ignore non-numeric speed rules
        if any(word in ms for word in ["national", "signals", "variable", "none", "walk"]):
            return None

        # extract number
        num = ""
        for c in ms:
            if c.isdigit() or c == ".":
                num += c
            elif num:
                break
        if not num:
            return None

        try:
            val = float(num)
        except ValueError:
            return None

        if "km" in ms:
            # km/h -> mph
            return int(round(val * 0.621371))
        if "mph" in ms:
            return int(round(val))
        # If unit is absent, assume mph for UK testing setup.
        return int(round(val))
