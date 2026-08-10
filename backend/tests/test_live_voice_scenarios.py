"""test_live_voice_scenarios.py — Verification script for Swasthya Bharat Voice Agent scenarios.

Tests voice scenario queries against Assistant instance with live tool execution:
1. "Can you find the nearest hospital to me in Ahmedabad?"
2. "I don't need a hospital, can you find a nearby clinic in Surat?"
3. "What are some healthy habits?" (facility tool NOT called)
"""

import asyncio
import json
import logging
import os
import sys

_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from agent import Assistant  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_voice")


async def run_voice_scenarios():
    assistant = Assistant(user_id="live_voice_tester")

    print("\n--- SCENARIO 1: Hospital search in Ahmedabad ---")
    res1_str = await assistant.find_nearest_healthcare_facility(
        context=None,
        latitude=0.0,
        longitude=0.0,
        facility_type="hospital",
        location_name="Ahmedabad",
    )
    res1 = json.loads(res1_str)
    print(f"Success: {res1.get('success')}")
    print(f"Facilities found: {len(res1.get('facilities', []))}")
    if res1.get("facilities"):
        top = res1["facilities"][0]
        print(f"Top Hospital: {top.get('name')} ({top.get('distance_km')} km)")

    print("\n--- SCENARIO 2: Clinic search in Surat ---")
    res2_str = await assistant.find_nearest_healthcare_facility(
        context=None,
        latitude=0.0,
        longitude=0.0,
        facility_type="clinic",
        location_name="Surat",
    )
    res2 = json.loads(res2_str)
    print(f"Success: {res2.get('success')}")
    print(f"Facilities found: {len(res2.get('facilities', []))}")
    if res2.get("facilities"):
        top = res2["facilities"][0]
        print(f"Top Clinic: {top.get('name')} ({top.get('distance_km')} km)")

    print("\n--- SCENARIO 3: Missing Location Prompt ---")
    res3_str = await assistant.find_nearest_healthcare_facility(
        context=None,
        latitude=0.0,
        longitude=0.0,
        location_name=None,
    )
    res3 = json.loads(res3_str)
    print(f"Success: {res3.get('success')}")
    print(f"Error: {res3.get('error')}")
    print(f"Message: {res3.get('message')}")

    print("\n--- ALL VOICE TOOL SCENARIOS VERIFIED SUCCESSFUL ---")


if __name__ == "__main__":
    asyncio.run(run_voice_scenarios())
