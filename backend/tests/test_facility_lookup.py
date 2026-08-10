"""test_facility_lookup.py — Unit tests for OpenStreetMap healthcare facility lookup.

Covers distance calculations, Overpass API query construction, data parsing,
distance sorting, facility filtering, timeout/error handling, missing location,
and field preservation (no fabricated metadata).
"""

import json
import os
import sys
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

# Ensure src is on sys.path
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import facility_lookup  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1 — Haversine Distance Calculation
# ---------------------------------------------------------------------------
def test_haversine_distance():
    """Verify distance between known coordinates (e.g. Ahmedabad to Gandhinagar ~25km)."""
    lat1, lon1 = 23.0225, 72.5714  # Ahmedabad
    lat2, lon2 = 23.2156, 72.6369  # Gandhinagar
    dist = facility_lookup.haversine_distance(lat1, lon1, lat2, lon2)
    assert 20.0 < dist < 30.0, f"Expected ~25km, got {dist:.2f}km"


def test_haversine_distance_zero():
    """Distance between same point should be 0.0."""
    dist = facility_lookup.haversine_distance(23.0225, 72.5714, 23.0225, 72.5714)
    assert dist == 0.0


# ---------------------------------------------------------------------------
# Test 2 — Geocoding Location via Nominatim (Mocked)
# ---------------------------------------------------------------------------
@patch("urllib.request.urlopen")
def test_geocode_location_success(mock_urlopen):
    """Test successful geocoding of city name."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(
        [
            {
                "lat": "23.0225",
                "lon": "72.5714",
                "display_name": "Ahmedabad, Gujarat, India",
            }
        ]
    ).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    coords = facility_lookup.geocode_location("Ahmedabad")
    assert coords is not None
    assert coords[0] == pytest.approx(23.0225)
    assert coords[1] == pytest.approx(72.5714)


@patch("urllib.request.urlopen")
def test_geocode_location_not_found(mock_urlopen):
    """Test geocoding for unknown location returns None."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps([]).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    coords = facility_lookup.geocode_location("NonExistentCityXYZ123")
    assert coords is None


# ---------------------------------------------------------------------------
# Test 3 — Successful Facility Lookup & Sorting by Distance (Mocked Overpass)
# ---------------------------------------------------------------------------
@patch("urllib.request.urlopen")
def test_query_facilities_success_and_sorting(mock_urlopen):
    """Facilities must be extracted, distance computed, and sorted nearest to farthest."""
    user_lat, user_lon = 23.0225, 72.5714  # Center point

    # Mock elements: one close hospital (1km), one farther hospital (5km)
    mock_overpass_resp = {
        "osm3s": {"timestamp_osm_base": "2026-08-10T12:00:00Z"},
        "elements": [
            {
                "type": "node",
                "id": 101,
                "lat": 23.0600,
                "lon": 72.5714,  # ~4.1 km away
                "tags": {
                    "amenity": "hospital",
                    "name": "Far Civil Hospital",
                    "phone": "+91-79-11111111",
                },
            },
            {
                "type": "node",
                "id": 102,
                "lat": 23.0300,
                "lon": 72.5714,  # ~0.83 km away
                "tags": {
                    "amenity": "hospital",
                    "name": "Near City Hospital",
                    "emergency": "yes",
                },
            },
        ],
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_overpass_resp).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    res = facility_lookup.query_overpass_facilities(
        latitude=user_lat, longitude=user_lon, facility_type="hospital", limit=3
    )

    assert res["success"] is True
    assert res["source"] == "OpenStreetMap"
    assert res["data_timestamp"] == "2026-08-10T12:00:00Z"
    facilities = res["facilities"]
    assert len(facilities) == 2

    # Check nearest first
    assert facilities[0]["name"] == "Near City Hospital"
    assert facilities[0]["distance_km"] < facilities[1]["distance_km"]
    assert facilities[0]["emergency"] == "yes"

    # Check second facility preserves phone
    assert facilities[1]["name"] == "Far Civil Hospital"
    assert facilities[1]["phone"] == "+91-79-11111111"


# ---------------------------------------------------------------------------
# Test 4 — Hospital Filtering
# ---------------------------------------------------------------------------
def test_hospital_filtering_query_building():
    """Verify hospital query contains amenity=hospital tags."""
    query = facility_lookup._build_overpass_query(
        23.0225, 72.5714, facility_type="hospital"
    )
    assert 'amenity"="hospital"' in query
    assert 'amenity"="clinic"' not in query


# ---------------------------------------------------------------------------
# Test 5 — Clinic Filtering
# ---------------------------------------------------------------------------
def test_clinic_filtering_query_building():
    """Verify clinic query contains amenity=clinic tags."""
    query = facility_lookup._build_overpass_query(
        23.0225, 72.5714, facility_type="clinic"
    )
    assert 'amenity"="clinic"' in query
    assert 'amenity"="hospital"' not in query


# ---------------------------------------------------------------------------
# Test 6 — Doctor & Health Post Filtering
# ---------------------------------------------------------------------------
def test_doctor_and_health_post_query_building():
    """Verify doctor and health post queries contain correct tags."""
    doc_query = facility_lookup._build_overpass_query(
        23.0225, 72.5714, facility_type="doctor"
    )
    assert 'amenity"="doctors"' in doc_query

    hp_query = facility_lookup._build_overpass_query(
        23.0225, 72.5714, facility_type="health_post"
    )
    assert 'amenity"="health_post"' in hp_query


# ---------------------------------------------------------------------------
# Test 7 — No Facilities Found
# ---------------------------------------------------------------------------
@patch("urllib.request.urlopen")
def test_query_facilities_none_found(mock_urlopen):
    """When Overpass returns 0 elements, result should indicate no facilities found."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({"elements": []}).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    res = facility_lookup.query_overpass_facilities(23.0225, 72.5714)
    assert res["success"] is True
    assert res["facilities"] == []
    assert "couldn't find a healthcare facility" in res["message"]


# ---------------------------------------------------------------------------
# Test 8 — API Timeout Handling
# ---------------------------------------------------------------------------
@patch("urllib.request.urlopen")
def test_query_facilities_timeout(mock_urlopen):
    """When network times out, function returns error response gracefully."""
    mock_urlopen.side_effect = TimeoutError("Connection timed out")

    res = facility_lookup.query_overpass_facilities(23.0225, 72.5714)
    assert res["success"] is False
    assert res["error"] == "timeout"
    assert "trouble accessing" in res["message"]


# ---------------------------------------------------------------------------
# Test 9 — API HTTP Error Handling
# ---------------------------------------------------------------------------
@patch("urllib.request.urlopen")
def test_query_facilities_http_error(mock_urlopen):
    """When HTTP error 500 or 429 occurs, function returns API error response."""
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="https://overpass-api.de/api/interpreter",
        code=500,
        msg="Internal Server Error",
        hdrs={},
        fp=None,
    )

    res = facility_lookup.query_overpass_facilities(23.0225, 72.5714)
    assert res["success"] is False
    assert res["error"] in ("api_error", "timeout")
    assert "trouble accessing" in res["message"]


# ---------------------------------------------------------------------------
# Test 10 — Missing Location Handling
# ---------------------------------------------------------------------------
def test_query_facilities_missing_location():
    """Lat/lon equal to 0.0 without location name returns missing_location error."""
    res = facility_lookup.query_overpass_facilities(0.0, 0.0)
    assert res["success"] is False
    assert res["error"] == "missing_location"
    assert "need your current city or location" in res["message"]


# ---------------------------------------------------------------------------
# Test 11 — Missing Facility Fields (No Fabrication)
# ---------------------------------------------------------------------------
@patch("urllib.request.urlopen")
def test_query_facilities_no_fabricated_fields(mock_urlopen):
    """Fields like phone, address, emergency, opening_hours must NOT be fabricated if missing in OSM."""
    mock_overpass_resp = {
        "elements": [
            {
                "type": "node",
                "id": 999,
                "lat": 23.0250,
                "lon": 72.5720,
                "tags": {
                    "amenity": "clinic",
                    # Note: No phone, address, emergency, or opening_hours tags
                },
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_overpass_resp).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    res = facility_lookup.query_overpass_facilities(23.0225, 72.5714)
    assert res["success"] is True
    assert len(res["facilities"]) == 1
    fac = res["facilities"][0]

    # Verify missing tags are NOT present in the returned dictionary
    assert "phone" not in fac
    assert "address" not in fac
    assert "emergency" not in fac
    assert "opening_hours" not in fac
    assert "name" not in fac  # name tag was also missing


# ---------------------------------------------------------------------------
# Test 12 — Way/Relation Center Coordinate Extraction
# ---------------------------------------------------------------------------
@patch("urllib.request.urlopen")
def test_query_facilities_extracts_center_for_ways(mock_urlopen):
    """OSM ways return building centers; test center lat/lon parsing."""
    mock_overpass_resp = {
        "elements": [
            {
                "type": "way",
                "id": 555,
                "center": {"lat": 23.0280, "lon": 72.5750},
                "tags": {
                    "amenity": "hospital",
                    "name": "Community Health Center",
                    "addr:full": "123 Main Road, Paldi",
                },
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_overpass_resp).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    res = facility_lookup.query_overpass_facilities(23.0225, 72.5714)
    assert res["success"] is True
    assert len(res["facilities"]) == 1
    fac = res["facilities"][0]
    assert fac["name"] == "Community Health Center"
    assert fac["address"] == "123 Main Road, Paldi"
    assert fac["latitude"] == 23.0280
    assert fac["longitude"] == 72.5750


# ---------------------------------------------------------------------------
# Test 13 — Live Integration Test against OpenStreetMap Overpass & Nominatim API
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_live_overpass_api_integration():
    """Manual/Live integration test querying real OpenStreetMap servers for Ahmedabad."""
    # Step 1: Live geocode
    coords = facility_lookup.geocode_location("Ahmedabad")
    assert coords is not None
    lat, lon = coords

    # Step 2: Live Overpass query
    res = facility_lookup.query_overpass_facilities(
        latitude=lat, longitude=lon, facility_type="hospital", radius_km=5.0, limit=3
    )

    assert res["success"] is True
    assert res["source"] == "OpenStreetMap"
    assert "facilities" in res
    assert len(res["facilities"]) > 0, (
        "Expected at least 1 hospital near Ahmedabad center"
    )
    top_hospital = res["facilities"][0]
    assert "distance_km" in top_hospital
    assert "type" in top_hospital
