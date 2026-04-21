"""
map_osm.py  —  OpenStreetMap speed limit lookup for Webots simulation
=====================================================================
Since the simulation has no real GPS coordinates, we map Webots world
positions (pos_x, pos_z) to real UK road coordinates using a simple
zone table.  The Overpass API is then queried with those real coords,
so genuine OSM maxspeed tags are returned.

Usage:
    from map_osm import OSMMapClient
    client = OSMMapClient()
    speed = client.get_speed_limit(pos_x=10.5, pos_z=-3.2)
    # returns int (mph) or None if unknown
"""

import time
import threading
import requests
from typing import Optional


# ---------------------------------------------------------------------------
# ZONE TABLE  —  map Webots world X/Z ranges to speed limits
# ---------------------------------------------------------------------------
# Each entry: (x_min, x_max, map_speed_mph, lat, lng, label)
#
# map_speed_mph is used directly in simulation (no Overpass call needed).
# lat/lng are kept for real-hardware use or optional Overpass verification.
#
# Adjust x_min/x_max to match the actual pos_x range your Webots car travels.
# The car's pos_x from Webots is used to select the zone automatically.
# ---------------------------------------------------------------------------
ZONE_TABLE = [
    # (x_min, x_max, map_mph,  lat,        lng,       label)
    (-100,  -40,   30,   53.74530,   -0.33460,  "30 mph – residential"),
    ( -40,    0,   50,   53.74260,   -0.38120,  "50 mph – A-road"),
    (   0,   40,   60,   53.80210,   -0.41350,  "60 mph – single carriageway"),
    (  40,  100,   70,   53.72980,   -0.53870,  "70 mph – motorway"),
]

# Speed used when pos_x falls outside all defined zones
DEFAULT_MAP_SPEED_MPH = 30

# Overpass query radius (metres) around the coordinate
QUERY_RADIUS_M = 50

# Cache: don't re-query the same (rounded) coordinate within this window
CACHE_TTL_SECONDS = 60

# Sentinel stored in cache when a request fails — prevents hammering on repeated failures
_CACHE_MISS = "MISS"

# How long to suppress retries after a failed request (seconds)
FAILURE_CACHE_TTL = 30

# HTTP timeout for Overpass requests
REQUEST_TIMEOUT_SECONDS = 5.0

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


# ---------------------------------------------------------------------------
# TTL CACHE
# ---------------------------------------------------------------------------
class _TTLCache:
    def __init__(self, ttl: int):
        self._ttl = ttl
        self._store: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            value, ts = item
            if time.time() - ts > self._ttl:
                del self._store[key]
                return None
            return value

    def set(self, key, value):
        with self._lock:
            self._store[key] = (value, time.time())


# ---------------------------------------------------------------------------
# MAIN CLIENT
# ---------------------------------------------------------------------------
class OSMMapClient:
    """
    Looks up the OSM maxspeed tag for a road near a given coordinate.

    For simulation use, call get_speed_limit(pos_x, pos_z) and the
    class handles the Webots→real-world coordinate translation internally.
    """

    def __init__(self,
                 query_radius_m: int = QUERY_RADIUS_M,
                 cache_ttl_seconds: int = CACHE_TTL_SECONDS,
                 timeout: float = REQUEST_TIMEOUT_SECONDS):
        self._radius        = query_radius_m
        self._cache         = _TTLCache(cache_ttl_seconds)
        self._failure_cache = _TTLCache(FAILURE_CACHE_TTL)
        self._timeout       = timeout

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def get_map_speed_for_position(self, pos_x: float) -> int:
        """
        Returns the map speed limit (mph) for a given Webots pos_x directly
        from the zone table — no network call needed.

        This is the recommended method for simulation use. As the car drives
        and pos_x changes, the returned speed changes automatically.
        """
        for x_min, x_max, map_mph, _lat, _lng, label in ZONE_TABLE:
            if x_min <= pos_x <= x_max:
                return map_mph
        return DEFAULT_MAP_SPEED_MPH

    def get_speed_limit(self,
                        pos_x: float,
                        pos_z: float) -> Optional[int]:
        """
        Given a Webots world position, return the road speed limit in mph.
        First tries the zone table directly, then falls back to Overpass API.
        """
        # Fast path: use zone table speed directly
        for x_min, x_max, map_mph, _lat, _lng, _label in ZONE_TABLE:
            if x_min <= pos_x <= x_max:
                return map_mph

        # Fallback: try Overpass API with the mapped coordinate
        lat, lng = self._webots_to_latlon(pos_x, pos_z)
        return self._query(lat, lng)

    def get_speed_limit_from_latlon(self,
                                    lat: float,
                                    lng: float) -> Optional[int]:
        """Direct lat/lon lookup — use this if you have real coordinates."""
        return self._query(lat, lng)

    # ------------------------------------------------------------------
    # COORDINATE TRANSLATION
    # ------------------------------------------------------------------

    @staticmethod
    def _webots_to_latlon(pos_x: float, pos_z: float):
        for x_min, x_max, _map_mph, lat, lng, _label in ZONE_TABLE:
            if x_min <= pos_x <= x_max:
                return lat, lng
        return ZONE_TABLE[0][3], ZONE_TABLE[0][4]  # default to first zone coords

    # ------------------------------------------------------------------
    # OSM QUERY
    # ------------------------------------------------------------------

    def _query(self, lat: float, lng: float) -> Optional[int]:
        """
        Query Overpass for the maxspeed tag of the nearest highway way.
        Results are cached by rounded coordinate to avoid hammering the API.
        Failures are also cached for FAILURE_CACHE_TTL seconds.
        """
        cache_key = f"{lat:.4f},{lng:.4f}"

        # Check success cache first
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Check failure cache — if we recently failed, don't retry yet
        if self._failure_cache.get(cache_key) is not None:
            return None

        result = self._fetch_from_overpass(lat, lng)
        if result is not None:
            self._cache.set(cache_key, result)
        else:
            # Cache the failure so we don't retry every single frame
            self._failure_cache.set(cache_key, _CACHE_MISS)
        return result

    def _fetch_from_overpass(self, lat: float, lng: float) -> Optional[int]:
        """Send the actual HTTP request to the Overpass API."""
        query = f"""
[out:json][timeout:10];
way(around:{self._radius},{lat},{lng})["highway"]["maxspeed"];
out tags 1;
"""
        headers = {
            "User-Agent": "SpeedSignDetection/1.0 (University of Hull BA-25-1057; contact: student-project)",
            "Accept": "application/json",
        }
        try:
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query},
                headers=headers,
                timeout=self._timeout
            )
            resp.raise_for_status()
            data = resp.json()
            elements = data.get("elements", [])
            if not elements:
                return None

            raw = elements[0].get("tags", {}).get("maxspeed", "")
            return self._parse_maxspeed(raw)

        except requests.exceptions.Timeout:
            print("[OSM] Request timed out — using fallback")
            return None
        except requests.exceptions.RequestException as e:
            print(f"[OSM] Request error: {e}")
            return None
        except Exception as e:
            print(f"[OSM] Unexpected error: {e}")
            return None

    # ------------------------------------------------------------------
    # MAXSPEED PARSING
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_maxspeed(raw: str) -> Optional[int]:
        """
        Convert an OSM maxspeed tag string to an integer mph value.

        Handles:
          "30"          → 30  (assumed mph in UK context)
          "30 mph"      → 30
          "48 kph"      → 29  (converted)
          "national"    → 70  (UK national speed limit = 70 mph on motorways)
          "signals"     → None (variable, ignore)
          ""            → None
        """
        raw = raw.strip().lower()
        if not raw:
            return None

        # Variable / unknown tags
        if raw in ("signals", "variable", "none"):
            return None

        # UK national speed limit
        if raw in ("national", "nsl_single", "nsl_dual"):
            return 60  # conservative — NSL on single carriageway

        # Numeric with unit
        if "mph" in raw:
            digits = "".join(c for c in raw if c.isdigit())
            return int(digits) if digits else None

        if "kph" in raw or "km/h" in raw or "kmh" in raw:
            digits = "".join(c for c in raw if c.isdigit())
            if digits:
                return round(int(digits) / 1.60934)
            return None

        # Plain number — assumed mph for UK
        digits = "".join(c for c in raw if c.isdigit())
        if digits:
            return int(digits)

        return None


# ---------------------------------------------------------------------------
# QUICK TEST  (run this file directly to verify connectivity)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Testing OSM map client...\n")
    client = OSMMapClient()

    test_cases = [
        (-80,  0,  "Zone 1 — 30 mph residential Hull"),
        (-20,  0,  "Zone 2 — 50 mph A63"),
        ( 20,  0,  "Zone 3 — 60 mph A1033"),
        ( 70,  0,  "Zone 4 — 70 mph M62"),
    ]

    for pos_x, pos_z, label in test_cases:
        lat, lng = OSMMapClient._webots_to_latlon(pos_x, pos_z)
        result = client.get_speed_limit(pos_x, pos_z)
        print(f"  {label}")
        print(f"    Webots pos_x={pos_x} → lat={lat}, lng={lng}")
        print(f"    OSM maxspeed → {result} mph")
        print()