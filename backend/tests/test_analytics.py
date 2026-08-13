"""
test_analytics.py — Day 8: Unit & Integration tests for Call Analytics Dashboard.

Tests cover:
  1. New call record creation
  2. Successful call count tracking
  3. Failed call count tracking
  4. Total calls count tracking
  5. Success rate calculation
  6. Zero-call edge case handling (prevents division by zero)
  7. Average call duration calculation & formatting
  8. Human escalation count tracking
  9. Emergency case count tracking
  10. Analytics API endpoint returns real database values
  11. Analytics metrics are dynamic and non-hardcoded
  12. Privacy protection — sensitive info is excluded from analytics response
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

# Ensure src/ is importable
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import memory as mem  # noqa: E402
import webhook_server  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Use a temporary SQLite database for each test to ensure test isolation."""
    test_db = tmp_path / "test_analytics.db"
    monkeypatch.setattr(mem, "_DB_PATH", test_db)
    monkeypatch.setattr(mem, "_DB_DIR", tmp_path)
    mem.init_db()
    yield test_db


# ===========================================================================
# Test 1 & 2 & 3 & 4 — Basic Call Recording & Metric Counts
# ===========================================================================


def test_record_call_and_basic_counts():
    """Test recording successful and failed calls and verifying counts."""
    now = datetime.now(timezone.utc).isoformat()

    # Record 1 successful call
    mem.record_call(
        call_id="call_001",
        user_id="user_1",
        started_at=now,
        ended_at=now,
        duration_seconds=120,
        outcome="successful",
        success_reason="Provided general health info",
        human_escalation=False,
        emergency_case=False,
    )

    # Record 1 failed call
    mem.record_call(
        call_id="call_002",
        user_id="user_2",
        started_at=now,
        ended_at=now,
        duration_seconds=45,
        outcome="failed",
        failure_reason="User disconnected early",
        human_escalation=False,
        emergency_case=False,
    )

    summary = mem.get_analytics_summary()
    assert summary["total_calls"] == 2
    assert summary["successful_calls"] == 1
    assert summary["failed_calls"] == 1


# ===========================================================================
# Test 5 & 6 — Success Rate & Zero-Call Guard
# ===========================================================================


def test_zero_call_case_prevents_division_by_zero():
    """When zero calls exist, success_rate must be 0 and average duration 0s without errors."""
    summary = mem.get_analytics_summary()
    assert summary["total_calls"] == 0
    assert summary["successful_calls"] == 0
    assert summary["failed_calls"] == 0
    assert summary["success_rate"] == 0
    assert summary["average_duration_seconds"] == 0
    assert summary["average_duration_formatted"] == "0s"
    assert summary["human_escalations"] == 0
    assert summary["emergency_cases"] == 0
    assert summary["recent_calls"] == []


def test_success_rate_calculation():
    """Test accurate percentage calculation (8 successful out of 10 = 80%)."""
    now = datetime.now(timezone.utc).isoformat()

    for i in range(8):
        mem.record_call(
            call_id=f"succ_{i}",
            user_id=f"user_{i}",
            started_at=now,
            ended_at=now,
            duration_seconds=60,
            outcome="successful",
        )

    for i in range(2):
        mem.record_call(
            call_id=f"fail_{i}",
            user_id=f"user_{i}",
            started_at=now,
            ended_at=now,
            duration_seconds=30,
            outcome="failed",
        )

    summary = mem.get_analytics_summary()
    assert summary["total_calls"] == 10
    assert summary["successful_calls"] == 8
    assert summary["failed_calls"] == 2
    assert summary["success_rate"] == 80


# ===========================================================================
# Test 7 — Average Call Duration & Formatting
# ===========================================================================


def test_average_call_duration_calculation_and_formatting():
    """Test average call duration calculation and format_duration string builder."""
    assert mem.format_duration(0) == "0s"
    assert mem.format_duration(45) == "45s"
    assert mem.format_duration(120) == "2m"
    assert mem.format_duration(134) == "2m 14s"

    now = datetime.now(timezone.utc).isoformat()

    # Call 1: 100s, Call 2: 200s -> Avg = 150s (2m 30s)
    mem.record_call(
        call_id="c1",
        user_id="u1",
        started_at=now,
        ended_at=now,
        duration_seconds=100,
        outcome="successful",
    )
    mem.record_call(
        call_id="c2",
        user_id="u2",
        started_at=now,
        ended_at=now,
        duration_seconds=200,
        outcome="successful",
    )

    summary = mem.get_analytics_summary()
    assert summary["average_duration_seconds"] == 150
    assert summary["average_duration_formatted"] == "2m 30s"


# ===========================================================================
# Test 8 & 9 — Human Escalations & Emergency Cases
# ===========================================================================


def test_human_escalations_and_emergency_cases_count():
    """Test counting human escalations and emergency cases."""
    now = datetime.now(timezone.utc).isoformat()

    # Normal successful call
    mem.record_call(
        call_id="norm_1",
        user_id="u1",
        started_at=now,
        ended_at=now,
        duration_seconds=60,
        outcome="successful",
        human_escalation=False,
        emergency_case=False,
    )

    # Call with human escalation
    mem.record_call(
        call_id="esc_1",
        user_id="u2",
        started_at=now,
        ended_at=now,
        duration_seconds=90,
        outcome="successful",
        human_escalation=True,
        emergency_case=False,
    )

    # Call with emergency case
    mem.record_call(
        call_id="emerg_1",
        user_id="u3",
        started_at=now,
        ended_at=now,
        duration_seconds=40,
        outcome="successful",
        human_escalation=False,
        emergency_case=True,
    )

    summary = mem.get_analytics_summary()
    assert summary["total_calls"] == 3
    assert summary["human_escalations"] == 1
    assert summary["emergency_cases"] == 1


# ===========================================================================
# Test 10 & 11 — Analytics Endpoint Dynamics
# ===========================================================================


@pytest.mark.asyncio
async def test_analytics_api_endpoint_dynamic():
    """Test GET /api/analytics returns real dynamic calculated values from DB."""
    app = webhook_server.create_app()
    async with TestClient(TestServer(app)) as client:
        # Initial check when 0 calls exist
        resp = await client.get("/api/analytics")
        assert resp.status == 200
        data = await resp.json()
        assert data["total_calls"] == 0

        # Add a call to DB
        now = datetime.now(timezone.utc).isoformat()
        mem.record_call(
            call_id="api_test_001",
            user_id="api_user",
            started_at=now,
            ended_at=now,
            duration_seconds=120,
            outcome="successful",
            human_escalation=True,
        )

        # Check endpoint updates dynamically
        resp2 = await client.get("/api/analytics")
        assert resp2.status == 200
        data2 = await resp2.json()
        assert data2["total_calls"] == 1
        assert data2["successful_calls"] == 1
        assert data2["success_rate"] == 100
        assert data2["human_escalations"] == 1


# ===========================================================================
# Test 12 — Privacy Audit
# ===========================================================================


def test_privacy_no_sensitive_info_in_analytics():
    """Ensure no medical details, phone numbers, transcripts, or credentials appear in analytics output."""
    now = datetime.now(timezone.utc).isoformat()

    mem.record_call(
        call_id="priv_001",
        user_id="+919876543210",
        started_at=now,
        ended_at=now,
        duration_seconds=110,
        outcome="successful",
        success_reason="General guidance provided",
        failure_reason=None,
        human_escalation=False,
        emergency_case=False,
    )

    summary = mem.get_analytics_summary()
    recent = summary["recent_calls"][0]

    # Verify masked user_id (phone number masked)
    assert recent["user_id_masked"] == "+91****3210"
    assert "+919876543210" not in str(recent)

    # Verify key metadata fields only
    assert set(recent.keys()) == {
        "call_id",
        "user_id_masked",
        "started_at",
        "duration_seconds",
        "duration_formatted",
        "outcome",
        "human_escalation",
        "emergency_case",
    }
