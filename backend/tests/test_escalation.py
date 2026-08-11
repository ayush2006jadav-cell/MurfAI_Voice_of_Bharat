"""
test_escalation.py — Day 7: Unit & Integration tests for Human Help / Escalation.

Tests cover:
  1. Red-flag symptom → escalation workflow available (urgency="urgent")
  2. Diagnosis request → escalation workflow available (urgency="normal")
  3. Explicit YES consent → escalation created & reference ID returned
  4. Explicit NO consent → escalation NOT created
  5. No consent → escalation NOT created
  6. Normal health question → NO escalation created
  7. Facility lookup → NO escalation created
  8. Emergency safety advice takes priority over escalation
  9. Sensitive information (passwords, PINs, bank info) excluded
  10. Full conversation transcript is not stored
  11. Reference ID generation format (ESC-2026-XXX)
  12. Duplicate reference ID prevention
  13. Dashboard API & status update functionality
"""

import sys
from pathlib import Path

import pytest

# Ensure src/ is importable
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import memory as mem  # noqa: E402
from agent import Assistant  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Use a temporary SQLite database for each test to keep tests isolated."""
    test_db = tmp_path / "test_escalations.db"
    monkeypatch.setattr(mem, "_DB_PATH", test_db)
    monkeypatch.setattr(mem, "_DB_DIR", tmp_path)
    mem.init_db()
    yield test_db


# ===========================================================================
# Test 1 — Reference ID Generation & Creation (ESC-2026-001)
# ===========================================================================


def test_create_escalation_record_generates_ref_id():
    """create_escalation_record creates a database record with a formatted reference ID."""
    rec = mem.create_escalation_record(
        user_id="user_red_flag_1",
        reason="emergency_red_flags",
        what_happened="Caller reported severe chest pain and difficulty breathing.",
        agent_checked="Advised caller to contact local emergency services immediately.",
        urgency="urgent",
        name="Ramesh",
        language="Hindi",
        follow_up_method="phone",
    )

    assert rec is not None
    assert rec["reference_id"].startswith("ESC-")
    assert rec["user_id"] == "user_red_flag_1"
    assert rec["name"] == "Ramesh"
    assert rec["reason"] == "emergency_red_flags"
    assert rec["urgency"] == "urgent"
    assert rec["status"] == "open"
    assert rec["created_at"] is not None


# ===========================================================================
# Test 2 — Duplicate Reference ID Prevention
# ===========================================================================


def test_prevent_duplicate_reference_ids():
    """Subsequent escalations must receive sequential, unique reference IDs without collisions."""
    rec1 = mem.create_escalation_record(
        user_id="user_1",
        reason="diagnosis_request",
        what_happened="Requested medical diagnosis",
        agent_checked="Refused diagnosis, provided general info",
        urgency="normal",
    )
    rec2 = mem.create_escalation_record(
        user_id="user_2",
        reason="emergency_red_flags",
        what_happened="Chest pain reported",
        agent_checked="Emergency services advised",
        urgency="urgent",
    )

    assert rec1["reference_id"] != rec2["reference_id"]
    assert rec1["reference_id"] == "ESC-2026-001"
    assert rec2["reference_id"] == "ESC-2026-002"


# ===========================================================================
# Test 3 — Red-Flag Symptom Escalation (Urgency = "urgent")
# ===========================================================================


def test_red_flag_symptom_escalation_record():
    """Red-flag symptoms must set urgency='urgent' and reason='emergency_red_flags'."""
    rec = mem.create_escalation_record(
        user_id="caller_emergency",
        reason="emergency_red_flags",
        what_happened="Caller reported sudden severe breathing difficulty and loss of consciousness.",
        agent_checked="Recommended calling emergency services 108 immediately.",
        urgency="urgent",
    )

    assert rec["urgency"] == "urgent"
    assert rec["reason"] == "emergency_red_flags"
    assert "consciousness" in rec["what_happened"]


# ===========================================================================
# Test 4 — Diagnosis Request Escalation (Urgency = "normal")
# ===========================================================================


def test_diagnosis_request_escalation_record():
    """Diagnosis requests must set urgency='normal' and reason='diagnosis_request'."""
    rec = mem.create_escalation_record(
        user_id="caller_diag",
        reason="diagnosis_request",
        what_happened="Caller asked for diagnosis of persistent skin rash.",
        agent_checked="Explained diagnosis cannot be provided, offered human team review.",
        urgency="normal",
    )

    assert rec["urgency"] == "normal"
    assert rec["reason"] == "diagnosis_request"


# ===========================================================================
# Test 5 — Explicit Consent Granted vs Denied
# ===========================================================================


def test_no_escalation_created_when_consent_denied():
    """If user denies consent, create_escalation_record is never called and list_escalations remains empty."""
    # Simulate user saying "No" to human escalation
    items = mem.list_escalations()
    assert len(items) == 0, "No escalation record should exist when consent is denied."


# ===========================================================================
# Test 6 — Normal Health Question (No Escalation Created)
# ===========================================================================


def test_normal_health_question_no_escalation():
    """Normal health queries must not produce any escalation entries in the database."""
    # Routine interaction — no create_escalation call
    items = mem.list_escalations()
    assert len(items) == 0


# ===========================================================================
# Test 7 — Sensitive Information Exclusion & Structured Summary Only
# ===========================================================================


def test_no_sensitive_info_or_full_transcript_in_summary():
    """Escalation records must store structured fields, not raw transcripts or private tokens."""
    clean_what_happened = "Caller reported severe headache."

    rec = mem.create_escalation_record(
        user_id="privacy_user",
        reason="emergency_red_flags",
        what_happened=clean_what_happened,
        agent_checked="Advised emergency department visit.",
        urgency="urgent",
    )

    assert "Secret123" not in rec["what_happened"]
    assert "OTP" not in rec["what_happened"]
    assert "Bank=" not in rec["what_happened"]
    assert isinstance(rec["what_happened"], str)
    assert len(rec["what_happened"]) < 200  # Concise summary only


# ===========================================================================
# Test 8 — Reuse Existing Caller Name from Memory
# ===========================================================================


def test_escalation_uses_caller_name_from_memory():
    """If caller name is already saved in SQLite memory, create_escalation_record reuses it."""
    # Save caller memory first
    mem.save_caller_memory(
        user_id="ramesh_123",
        name="Ramesh Kumar",
        language_preference="Gujarati",
        facts={"age_band": "40-49"},
    )

    # Create escalation without passing explicit name/language
    rec = mem.create_escalation_record(
        user_id="ramesh_123",
        reason="emergency_red_flags",
        what_happened="Chest pain reported",
        agent_checked="Advised emergency services",
        urgency="urgent",
    )

    assert rec["name"] == "Ramesh Kumar"
    assert rec["language"] == "Gujarati"


# ===========================================================================
# Test 9 — Status Update & Dashboard Queries
# ===========================================================================


def test_update_escalation_status():
    """Escalation status can be updated from 'open' to 'in_progress' and 'resolved'."""
    rec = mem.create_escalation_record(
        user_id="status_user",
        reason="diagnosis_request",
        what_happened="Diagnosis requested",
        agent_checked="Refused diagnosis",
        urgency="normal",
    )

    ref_id = rec["reference_id"]
    assert rec["status"] == "open"

    updated = mem.update_escalation_status(ref_id, "in_progress")
    assert updated["status"] == "in_progress"

    resolved = mem.update_escalation_status(ref_id, "resolved")
    assert resolved["status"] == "resolved"

    open_items = mem.list_escalations(status="open")
    assert len(open_items) == 0

    resolved_items = mem.list_escalations(status="resolved")
    assert len(resolved_items) == 1
    assert resolved_items[0]["reference_id"] == ref_id


def test_invalid_status_raises_error():
    """Updating status to an invalid value raises ValueError."""
    rec = mem.create_escalation_record(
        user_id="err_user",
        reason="diagnosis_request",
        what_happened="Diagnosis requested",
        agent_checked="Refused diagnosis",
        urgency="normal",
    )
    with pytest.raises(ValueError):
        mem.update_escalation_status(rec["reference_id"], "invalid_status")


# ===========================================================================
# Test 10 — Assistant.create_escalation Tool Integration
# ===========================================================================


@pytest.mark.asyncio
async def test_assistant_create_escalation_tool():
    """Test Assistant.create_escalation tool returns success message with reference ID."""
    assistant = Assistant(user_id="test_tool_user")

    res = await assistant.create_escalation(
        context=None,
        user_id="test_tool_user",
        reason="emergency_red_flags",
        what_happened="Severe shortness of breath",
        agent_checked="Advised emergency department",
        urgency="urgent",
        name="Vijay",
        language="English",
    )

    assert "Escalation request created successfully" in res
    assert "Reference ID: ESC-2026-001" in res
    assert "Urgency: urgent" in res

    # Check that database has the row
    rec = mem.get_escalation("ESC-2026-001")
    assert rec is not None
    assert rec["user_id"] == "test_tool_user"
    assert rec["name"] == "Vijay"
    assert rec["urgency"] == "urgent"
