"""
test_memory.py — Unit tests for the Swasthya Bharat persistent caller memory module.

These tests exercise the SQLite memory helpers directly (no LiveKit infrastructure).
They use a temporary in-memory / temp-file database so they never touch production data.
"""

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Ensure the src package is importable when running from the tests/ directory
# ---------------------------------------------------------------------------
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import memory as mem  # noqa: E402  (import after path manipulation)


# ---------------------------------------------------------------------------
# Fixture: redirect the DB to a temporary file for each test
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Override the DB path to a fresh temp file for each test."""
    test_db = tmp_path / "test_memory.db"
    monkeypatch.setattr(mem, "_DB_PATH", test_db)
    monkeypatch.setattr(mem, "_DB_DIR", tmp_path)
    mem.init_db()
    yield test_db


# ===========================================================================
# Test 1 — New Caller: lookup returns None for unknown user_id
# ===========================================================================
def test_lookup_caller_not_found():
    """A completely new user_id should return None."""
    result = mem.lookup_caller("user_brand_new")
    assert result is None


# ===========================================================================
# Test 2 — Consent Granted: save and then look up a caller
# ===========================================================================
def test_save_and_lookup_caller():
    """After save_caller_memory is called, lookup_caller should return the record."""
    uid = "ramesh_123"
    facts = {"age_band": "40-49", "ongoing_condition": "diabetes"}

    mem.save_caller_memory(
        user_id=uid,
        name="Ramesh",
        language_preference="Hindi",
        facts=facts,
    )

    record = mem.lookup_caller(uid)
    assert record is not None
    assert record["user_id"] == uid
    assert record["name"] == "Ramesh"
    assert record["language_preference"] == "Hindi"
    assert record["facts"]["age_band"] == "40-49"
    assert record["facts"]["ongoing_condition"] == "diabetes"
    assert record["last_interaction"] is not None


# ===========================================================================
# Test 3 — Consent Denied: save is never called → record stays absent
# ===========================================================================
def test_no_save_when_consent_denied():
    """If the agent honours a NO, save_caller_memory is never called — verify by not calling it."""
    uid = "priya_456"
    # Simulate consent denied: we simply do NOT call save_caller_memory
    result = mem.lookup_caller(uid)
    assert result is None, "No record should exist when save was never called"


# ===========================================================================
# Test 4 — Returning Caller: upsert merges new facts with existing ones
# ===========================================================================
def test_update_caller_memory_merges_facts():
    """A second save_caller_memory call should update and merge, not overwrite."""
    uid = "vijay_789"

    mem.save_caller_memory(
        user_id=uid,
        name="Vijay",
        language_preference="Gujarati",
        facts={"age_band": "30-39"},
    )
    # Second call — add a new fact, keep old ones
    mem.save_caller_memory(
        user_id=uid,
        name=None,
        language_preference=None,
        facts={"last_triage_outcome": "recommended doctor consultation"},
    )

    record = mem.lookup_caller(uid)
    assert record is not None
    assert record["name"] == "Vijay"  # preserved from first save
    assert record["language_preference"] == "Gujarati"  # preserved
    assert record["facts"]["age_band"] == "30-39"  # preserved
    assert (
        record["facts"]["last_triage_outcome"] == "recommended doctor consultation"
    )  # newly added


# ===========================================================================
# Test 5 — Database Persistence: re-initialising the DB does not clear data
# ===========================================================================
def test_facts_persist_across_init(isolated_db):
    """Calling init_db() again (simulating a restart) must not wipe existing rows."""
    uid = "meena_persistence"
    mem.save_caller_memory(
        uid, name="Meena", language_preference="English", facts={"age_band": "50-59"}
    )

    # Simulate restart: call init_db() again (CREATE TABLE IF NOT EXISTS is idempotent)
    mem.init_db()

    record = mem.lookup_caller(uid)
    assert record is not None
    assert record["name"] == "Meena"
    assert record["facts"]["age_band"] == "50-59"


# ===========================================================================
# Test 6 — Healthcare Privacy: facts are stored as structured fields, not transcripts
# ===========================================================================
def test_only_structured_facts_stored():
    """Facts must be a dict of discrete fields, not a freeform transcript."""
    uid = "health_privacy_user"
    structured_facts = {
        "age_band": "20-29",
        "ongoing_condition": "asthma",
        "last_triage_outcome": "recommended PHC visit",
    }
    mem.save_caller_memory(
        uid, name="Ananya", language_preference="English", facts=structured_facts
    )

    record = mem.lookup_caller(uid)
    stored_facts = record["facts"]

    # Must be a plain dict (not a raw conversation string)
    assert isinstance(stored_facts, dict)
    # Must have no more than 4 keys (privacy constraint)
    assert len(stored_facts) <= 4
    # Keys must be structured field names, not arbitrary paragraphs
    for key in stored_facts:
        assert " " not in key, f"Fact key '{key}' looks like freeform text"


# ===========================================================================
# Test 7 — Returning Caller Recognition: lookup returns name for personalised greeting
# ===========================================================================
def test_returning_caller_name_available_for_greeting():
    """When a returning caller is looked up, their name is available for a personalised greeting."""
    uid = "suresh_returning"
    mem.save_caller_memory(
        uid, name="Suresh", language_preference="Gujarati", facts={"age_band": "60-69"}
    )

    record = mem.lookup_caller(uid)
    assert record is not None
    # The agent should be able to greet the caller by name
    assert record["name"] == "Suresh"
    # Language preference is available to set the response language
    assert record["language_preference"] == "Gujarati"


# ===========================================================================
# Test 8 — user_id normalisation (case and whitespace)
# ===========================================================================
def test_user_id_normalised():
    """user_id should be lowercased and stripped of surrounding whitespace."""
    mem.save_caller_memory(
        "  Alice_007  ", name="Alice", language_preference="English", facts={}
    )
    assert mem.lookup_caller("alice_007") is not None
    assert mem.lookup_caller("  Alice_007  ") is not None


# ===========================================================================
# Test 9 — Empty user_id returns None gracefully
# ===========================================================================
def test_lookup_empty_user_id_returns_none():
    """An empty or whitespace-only user_id should return None without error."""
    assert mem.lookup_caller("") is None
    assert mem.lookup_caller("   ") is None
