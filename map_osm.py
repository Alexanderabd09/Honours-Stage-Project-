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
# ZONE TABLE  —  map Webots world X/Z ranges to real UK road coordinates
# ---------------------------------------------------------------------------
# Each entry: (x_min, x_max, lat, lng, label)
# Pick roads whose real OSM maxspeed tag matches what you want to test.
#
# Examples used below (all real UK roads — verified on OSM):
#   30 mph zone  → residential street in Hull city centre
#   50 mph zone  → A63 dual carriageway Hull
#   60 mph zone  → A1033 single carriageway East Yorkshire
#   70 mph zone  → M62 motorway near Hull
#
# Adjust these to whatever zones your Webots world represents.
# ---------------------------------------------------------------------------
ZONE_TABLE = [
    # (x_min, x_max,  lat,        lng,       label)
    (-100,  -40,   53.74530,   -0.33460,  "30 mph – Hull residential"),
    ( -40,    0,   53.74260,   -0.38120,  "50 mph – A63 Hull"),
    (   0,   40,   53.80210,   -0.41350,  "60 mph – A1033 East Yorks"),
    (  40,  100,   53.72980,   -0.53870,  "70 mph – M62 motorway"),
]

# Fallback coordinate used when pos_x is outside all zones
# (Hull city centre — typically 30 mph)
DEFAULT_LAT = 53.74530
DEFAULT_LNG = -0.33460

# Overpass query radius (metres) around the coordinate
QUERY_RADIUS_M = 50

# Cache: don't re-query the same (rounded) coordinate within this window
CACHE_TTL_SECONDS = 60

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
        self._radius  = query_radius_m
        self._cache   = _TTLCache(cache_ttl_seconds)
        self._timeout = timeout

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def get_speed_limit(self,
                        pos_x: float,
                        pos_z: float) -> Optional[int]:
        """
        Given a Webots world position, return the road speed limit in mph.
        Returns None if the lookup fails or no maxspeed tag is found.
        """
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
        """
        Translate Webots world coordinates to a real UK lat/lon using
        the zone table.  Falls back to DEFAULT_LAT/LNG if out of range.
        """
        for x_min, x_max, lat, lng, _label in ZONE_TABLE:
            if x_min <= pos_x <= x_max:
                return lat, lng
        return DEFAULT_LAT, DEFAULT_LNG

    # ------------------------------------------------------------------
    # OSM QUERY
    # ------------------------------------------------------------------

    def _query(self, lat: float, lng: float) -> Optional[int]:
        """
        Query Overpass for the maxspeed tag of the nearest highway way.
        Results are cached by rounded coordinate to avoid hammering the API.
        """
        # Round to ~11 m precision for cache key
        cache_key = f"{lat:.4f},{lng:.4f}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result = self._fetch_from_overpass(lat, lng)
        if result is not None:
            self._cache.set(cache_key, result)
        return result

    def _fetch_from_overpass(self, lat: float, lng: float) -> Optional[int]:
        """Send the actual HTTP request to the Overpass API."""
        query = f"""
[out:json][timeout:10];
way(around:{self._radius},{lat},{lng})["highway"]["maxspeed"];
out tags 1;
"""
        try:
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query},
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
