"""facility_lookup.py — Real-domain healthcare facility search using OpenStreetMap.

Fetches real healthcare facilities (hospitals, clinics, doctors, health posts)
around a set of geographic coordinates using the Overpass API, and provides
geocoding capabilities via OpenStreetMap Nominatim.
"""

import datetime
import json
import logging
import math
import socket
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("facility_lookup")

# User-Agent header for OpenStreetMap usage policy compliance
USER_AGENT = (
    "SwasthyaBharatVoiceAgent/1.0 (health-access-assistant; contact@swasthyabharat.org)"
)

# Primary Overpass API endpoints (main and fallback)
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Nominatim API endpoint for geocoding place names
NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/search"


def haversine_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Calculate the great-circle distance between two points on the Earth in kilometers.

    Uses the Haversine formula.
    """
    r = 6371.0  # Earth's mean radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def geocode_location(
    location_name: str,
    timeout_seconds: float = 10.0,
) -> tuple[float, float] | None:
    """Geocode a location or city name into (latitude, longitude) using OpenStreetMap Nominatim.

    Returns None if location is not found or if the request fails.
    """
    if not location_name or not location_name.strip():
        return None

    params = {
        "q": location_name.strip(),
        "format": "json",
        "limit": "1",
    }
    url = f"{NOMINATIM_ENDPOINT}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    try:
        logger.info("Geocoding location %r via Nominatim...", location_name)
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            if resp.status != 200:
                logger.warning("Nominatim HTTP status: %d", resp.status)
                return None
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0:
                first = data[0]
                lat = float(first["lat"])
                lon = float(first["lon"])
                logger.info(
                    "Geocoded %r to lat=%.5f, lon=%.5f", location_name, lat, lon
                )
                return lat, lon
            logger.info("Nominatim returned no results for %r", location_name)
            return None
    except Exception as e:
        logger.warning("Geocoding failed for %r: %s", location_name, e)
        return None


def _build_overpass_query(
    latitude: float,
    longitude: float,
    facility_type: str = "any",
    radius_meters: int = 10000,
) -> str:
    """Construct an Overpass QL query string based on requested facility_type."""
    fac_clean = facility_type.strip().lower()

    # Map facility_type to specific OSM tag queries
    if fac_clean in ("hospital", "hospitals"):
        tag_queries = [
            f'node["amenity"="hospital"](around:{radius_meters},{latitude},{longitude});',
            f'way["amenity"="hospital"](around:{radius_meters},{latitude},{longitude});',
            f'relation["amenity"="hospital"](around:{radius_meters},{latitude},{longitude});',
            f'node["healthcare"="hospital"](around:{radius_meters},{latitude},{longitude});',
            f'way["healthcare"="hospital"](around:{radius_meters},{latitude},{longitude});',
            f'relation["healthcare"="hospital"](around:{radius_meters},{latitude},{longitude});',
        ]
    elif fac_clean in ("clinic", "clinics"):
        tag_queries = [
            f'node["amenity"="clinic"](around:{radius_meters},{latitude},{longitude});',
            f'way["amenity"="clinic"](around:{radius_meters},{latitude},{longitude});',
            f'relation["amenity"="clinic"](around:{radius_meters},{latitude},{longitude});',
            f'node["healthcare"="clinic"](around:{radius_meters},{latitude},{longitude});',
            f'way["healthcare"="clinic"](around:{radius_meters},{latitude},{longitude});',
            f'relation["healthcare"="clinic"](around:{radius_meters},{latitude},{longitude});',
            f'node["healthcare"="centre"](around:{radius_meters},{latitude},{longitude});',
            f'way["healthcare"="centre"](around:{radius_meters},{latitude},{longitude});',
            f'relation["healthcare"="centre"](around:{radius_meters},{latitude},{longitude});',
        ]
    elif fac_clean in ("doctor", "doctors", "doctor's office", "doctors office"):
        tag_queries = [
            f'node["amenity"="doctors"](around:{radius_meters},{latitude},{longitude});',
            f'way["amenity"="doctors"](around:{radius_meters},{latitude},{longitude});',
            f'relation["amenity"="doctors"](around:{radius_meters},{latitude},{longitude});',
            f'node["healthcare"="doctor"](around:{radius_meters},{latitude},{longitude});',
            f'way["healthcare"="doctor"](around:{radius_meters},{latitude},{longitude});',
            f'relation["healthcare"="doctor"](around:{radius_meters},{latitude},{longitude});',
        ]
    elif fac_clean in ("health_post", "health post", "phc"):
        tag_queries = [
            f'node["amenity"="health_post"](around:{radius_meters},{latitude},{longitude});',
            f'way["amenity"="health_post"](around:{radius_meters},{latitude},{longitude});',
            f'relation["amenity"="health_post"](around:{radius_meters},{latitude},{longitude});',
            f'node["healthcare"="health_post"](around:{radius_meters},{latitude},{longitude});',
            f'way["healthcare"="health_post"](around:{radius_meters},{latitude},{longitude});',
            f'relation["healthcare"="health_post"](around:{radius_meters},{latitude},{longitude});',
        ]
    else:  # "any" or unsupported type -> search all standard healthcare facility tags
        tag_queries = [
            f'node["amenity"="hospital"](around:{radius_meters},{latitude},{longitude});',
            f'way["amenity"="hospital"](around:{radius_meters},{latitude},{longitude});',
            f'relation["amenity"="hospital"](around:{radius_meters},{latitude},{longitude});',
            f'node["amenity"="clinic"](around:{radius_meters},{latitude},{longitude});',
            f'way["amenity"="clinic"](around:{radius_meters},{latitude},{longitude});',
            f'relation["amenity"="clinic"](around:{radius_meters},{latitude},{longitude});',
            f'node["amenity"="doctors"](around:{radius_meters},{latitude},{longitude});',
            f'way["amenity"="doctors"](around:{radius_meters},{latitude},{longitude});',
            f'relation["amenity"="doctors"](around:{radius_meters},{latitude},{longitude});',
            f'node["amenity"="health_post"](around:{radius_meters},{latitude},{longitude});',
            f'way["amenity"="health_post"](around:{radius_meters},{latitude},{longitude});',
            f'relation["amenity"="health_post"](around:{radius_meters},{latitude},{longitude});',
            f'node["healthcare"~"hospital|clinic|doctor|health_post|centre"](around:{radius_meters},{latitude},{longitude});',
            f'way["healthcare"~"hospital|clinic|doctor|health_post|centre"](around:{radius_meters},{latitude},{longitude});',
            f'relation["healthcare"~"hospital|clinic|doctor|health_post|centre"](around:{radius_meters},{latitude},{longitude});',
        ]

    query_body = "\n  ".join(tag_queries)
    return f"[out:json][timeout:15];\n(\n  {query_body}\n);\nout center;"


def _extract_address(tags: dict[str, str]) -> str | None:
    """Extract address from OSM tags if present. Do not invent missing data."""
    if "addr:full" in tags:
        return tags["addr:full"].strip()

    parts = []
    for key in [
        "addr:housenumber",
        "addr:street",
        "addr:suburb",
        "addr:district",
        "addr:city",
        "addr:postcode",
    ]:
        if key in tags and tags[key].strip():
            parts.append(tags[key].strip())

    return ", ".join(parts) if parts else None


def query_overpass_facilities(
    latitude: float,
    longitude: float,
    facility_type: str = "any",
    radius_km: float = 10.0,
    limit: int = 3,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Query real healthcare facilities from OpenStreetMap via Overpass API.

    Calculates Haversine distance, sorts facilities from closest to farthest,
    and returns structured result dict.
    """
    if latitude == 0.0 and longitude == 0.0:
        return {
            "success": False,
            "error": "missing_location",
            "message": "I can find nearby healthcare facilities, but I need your current city or location first.",
        }

    radius_meters = int(max(0.5, radius_km) * 1000)
    query_str = _build_overpass_query(
        latitude=latitude,
        longitude=longitude,
        facility_type=facility_type,
        radius_meters=radius_meters,
    )

    data_payload = urllib.parse.urlencode({"data": query_str}).encode("utf-8")
    queried_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    json_resp: dict[str, Any] | None = None
    last_error: Exception | None = None

    for endpoint in OVERPASS_ENDPOINTS:
        req = urllib.request.Request(
            endpoint,
            data=data_payload,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json",
            },
        )
        try:
            logger.info(
                "Querying Overpass API at %s for lat=%.5f lon=%.5f (type=%s, radius=%.1fkm)...",
                endpoint,
                latitude,
                longitude,
                facility_type,
                radius_km,
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                if resp.status == 200:
                    raw_text = resp.read().decode("utf-8")
                    json_resp = json.loads(raw_text)
                    break
                else:
                    logger.warning(
                        "Overpass endpoint %s returned status %d", endpoint, resp.status
                    )
        except Exception as e:
            logger.warning("Overpass endpoint %s failed: %s", endpoint, e)
            last_error = e

    if json_resp is None:
        logger.error("All Overpass API endpoints failed. Last error: %s", last_error)
        is_timeout = isinstance(last_error, (TimeoutError, socket.timeout))
        return {
            "success": False,
            "error": "timeout" if is_timeout else "api_error",
            "message": "I'm having trouble accessing the healthcare facility database right now. I don't want to give you an unverified location. Please try again in a moment.",
        }

    osm_data_timestamp = json_resp.get("osm3s", {}).get("timestamp_osm_base")
    elements = json_resp.get("elements", [])

    facilities = []
    seen_ids = set()

    for elem in elements:
        elem_id = f"{elem.get('type')}_{elem.get('id')}"
        if elem_id in seen_ids:
            continue
        seen_ids.add(elem_id)

        # Extract coordinates from node lat/lon or way/relation center
        elem_lat: float | None = elem.get("lat")
        elem_lon: float | None = elem.get("lon")
        if elem_lat is None or elem_lon is None:
            center = elem.get("center")
            if isinstance(center, dict):
                elem_lat = center.get("lat")
                elem_lon = center.get("lon")

        if elem_lat is None or elem_lon is None:
            continue

        dist_km = haversine_distance(latitude, longitude, elem_lat, elem_lon)
        tags: dict[str, str] = elem.get("tags", {})

        # Determine facility type name
        amenity = tags.get("amenity", "")
        healthcare = tags.get("healthcare", "")
        fac_type = (
            amenity
            or healthcare
            or (facility_type if facility_type != "any" else "healthcare_facility")
        )

        # Extract fields ONLY if they actually exist in OSM tags (no fabrication)
        fac_dict: dict[str, Any] = {
            "type": fac_type,
            "distance_km": round(dist_km, 2),
            "latitude": elem_lat,
            "longitude": elem_lon,
        }

        name = tags.get("name") or tags.get("name:en") or tags.get("name:gu")
        if name:
            fac_dict["name"] = name.strip()

        address = _extract_address(tags)
        if address:
            fac_dict["address"] = address

        phone = tags.get("phone") or tags.get("contact:phone")
        if phone:
            fac_dict["phone"] = phone.strip()

        emergency = tags.get("emergency")
        if emergency:
            fac_dict["emergency"] = emergency.strip()

        opening_hours = tags.get("opening_hours")
        if opening_hours:
            fac_dict["opening_hours"] = opening_hours.strip()

        facilities.append(fac_dict)

    # Sort facilities by nearest distance
    facilities.sort(key=lambda f: f["distance_km"])

    # Limit results
    results = facilities[:limit]

    res_dict: dict[str, Any] = {
        "success": True,
        "source": "OpenStreetMap",
        "queried_at": queried_at,
        "facilities": results,
    }

    if osm_data_timestamp:
        res_dict["data_timestamp"] = osm_data_timestamp

    if not results:
        res_dict["message"] = (
            "I couldn't find a healthcare facility in the searched area. Would you like me to search a wider area?"
        )

    return res_dict
