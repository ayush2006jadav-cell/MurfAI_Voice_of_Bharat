"""
memory.py — Persistent caller memory for Swasthya Bharat.

Provides two simple functions used as agent tools:
  - lookup_caller(user_id)
  - save_caller_memory(user_id, name, language_preference, facts)

Storage: SQLite (stdlib), one table, one row per caller.
Database location: <backend_root>/data/swasthya_memory.db

HEALTHCARE PRIVACY NOTICE:
  Only minimum structured facts are stored (age_band, ongoing_condition,
  last_triage_outcome). Full conversation transcripts and detailed medical
  notes are NEVER stored. Information is only saved with explicit caller
  consent obtained by the agent.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("agent.memory")

# DB lives in backend/data/ — created automatically, persists across restarts.
_DB_DIR = Path(__file__).resolve().parent.parent / "data"
_DB_PATH = _DB_DIR / "swasthya_memory.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS callers (
    user_id             TEXT PRIMARY KEY,
    name                TEXT,
    language_preference TEXT,
    facts               TEXT,
    last_interaction    TEXT
);

CREATE TABLE IF NOT EXISTS escalations (
    reference_id      TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL,
    name              TEXT,
    reason            TEXT NOT NULL,
    what_happened     TEXT NOT NULL,
    agent_checked     TEXT NOT NULL,
    urgency           TEXT NOT NULL,
    language          TEXT,
    follow_up_method  TEXT,
    created_at        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS calls (
    call_id          TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    ended_at         TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    outcome          TEXT NOT NULL,
    success_reason   TEXT,
    failure_reason   TEXT,
    human_escalation INTEGER NOT NULL DEFAULT 0,
    emergency_case   INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);
"""


def init_db() -> None:
    """Create the database and tables if they do not already exist.

    Call this once at agent startup (inside my_agent).
    """
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.executescript(_CREATE_TABLE_SQL)
    logger.info("Memory DB ready at %s", _DB_PATH)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def lookup_caller(user_id: str) -> dict | None:
    """Return the stored record for *user_id*, or None if not found.

    Returns a plain dict with keys:
        user_id, name, language_preference, facts (dict), last_interaction
    """
    if not user_id or not user_id.strip():
        return None
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM callers WHERE user_id = ?", (user_id.strip().lower(),)
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    # Deserialise the JSON facts field back to a dict
    try:
        result["facts"] = json.loads(result["facts"] or "{}")
    except (json.JSONDecodeError, TypeError):
        result["facts"] = {}
    return result


def save_caller_memory(
    user_id: str,
    name: str | None = None,
    language_preference: str | None = None,
    facts: dict | None = None,
) -> dict:
    """Create or update the caller record and set last_interaction to now.

    Performs an UPSERT so existing fields are preserved when arguments are None.
    Returns the final stored record.
    """
    uid = user_id.strip().lower()
    now = datetime.now(timezone.utc).isoformat()

    existing = lookup_caller(uid)

    merged_name = name if name is not None else (existing or {}).get("name")
    merged_lang = (
        language_preference
        if language_preference is not None
        else (existing or {}).get("language_preference")
    )
    merged_facts = (existing or {}).get("facts", {}) if existing else {}
    if facts:
        merged_facts.update(facts)

    facts_json = json.dumps(merged_facts, ensure_ascii=False)

    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO callers (user_id, name, language_preference, facts, last_interaction)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name                = excluded.name,
                language_preference = excluded.language_preference,
                facts               = excluded.facts,
                last_interaction    = excluded.last_interaction
            """,
            (uid, merged_name, merged_lang, facts_json, now),
        )
    logger.info("Saved memory for caller '%s'", uid)
    return lookup_caller(uid)  # type: ignore[return-value]


# ===========================================================================
# Day 7 — Human Help & Escalation Database Helpers
# ===========================================================================


def _generate_reference_id(conn: sqlite3.Connection) -> str:
    """Generate a unique reference ID in format ESC-2026-001."""
    year = datetime.now(timezone.utc).year
    cursor = conn.execute("SELECT COUNT(*) FROM escalations")
    count = cursor.fetchone()[0] + 1

    while True:
        ref_id = f"ESC-{year}-{count:03d}"
        exists = conn.execute(
            "SELECT 1 FROM escalations WHERE reference_id = ?", (ref_id,)
        ).fetchone()
        if not exists:
            return ref_id
        count += 1


def create_escalation_record(
    user_id: str,
    reason: str,
    what_happened: str,
    agent_checked: str,
    urgency: str = "normal",
    name: str | None = None,
    language: str | None = None,
    follow_up_method: str | None = "phone",
) -> dict:
    """Create a new human escalation record and store it in SQLite.

    Generates a unique reference ID (e.g. ESC-2026-001) and returns the full record.
    """
    uid = user_id.strip().lower()
    now = datetime.now(timezone.utc).isoformat()

    # Look up existing caller memory if name/language are not provided
    existing = lookup_caller(uid)
    final_name = name if name else (existing or {}).get("name")
    final_lang = language if language else (existing or {}).get("language_preference")

    with _get_conn() as conn:
        ref_id = _generate_reference_id(conn)
        conn.execute(
            """
            INSERT INTO escalations (
                reference_id, user_id, name, reason, what_happened,
                agent_checked, urgency, language, follow_up_method,
                created_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """,
            (
                ref_id,
                uid,
                final_name,
                reason.strip(),
                what_happened.strip(),
                agent_checked.strip(),
                urgency.strip().lower(),
                final_lang,
                follow_up_method,
                now,
            ),
        )

    logger.info("Created escalation %s for user_id=%r", ref_id, uid)
    return get_escalation(ref_id)  # type: ignore[return-value]


def get_escalation(reference_id: str) -> dict | None:
    """Fetch an escalation record by reference_id, or None if not found."""
    if not reference_id or not reference_id.strip():
        return None
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM escalations WHERE reference_id = ?",
            (reference_id.strip().upper(),),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_escalations(status: str | None = None) -> list[dict]:
    """Return all escalation records, optionally filtered by status, ordered newest first."""
    with _get_conn() as conn:
        if status and status.strip():
            rows = conn.execute(
                "SELECT * FROM escalations WHERE status = ? ORDER BY created_at DESC",
                (status.strip().lower(),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM escalations ORDER BY created_at DESC"
            ).fetchall()
    return [dict(row) for row in rows]


def update_escalation_status(reference_id: str, status: str) -> dict | None:
    """Update status of an escalation ('open', 'in_progress', 'resolved')."""
    valid_statuses = {"open", "in_progress", "resolved"}
    st = status.strip().lower()
    if st not in valid_statuses:
        raise ValueError(f"Invalid status {status!r}. Must be one of {valid_statuses}")

    ref_id = reference_id.strip().upper()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE escalations SET status = ? WHERE reference_id = ?",
            (st, ref_id),
        )
    return get_escalation(ref_id)


# ===========================================================================
# Day 8 — Call Analytics Database Helpers
# ===========================================================================


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human-readable string (e.g. 134 -> '2m 14s', 45 -> '45s')."""
    if seconds <= 0:
        return "0s"
    minutes = seconds // 60
    rem_seconds = seconds % 60
    if minutes == 0:
        return f"{rem_seconds}s"
    if rem_seconds == 0:
        return f"{minutes}m"
    return f"{minutes}m {rem_seconds}s"


def mask_user_id(user_id: str) -> str:
    """Mask sensitive user identifiers for privacy in public dashboard tables."""
    uid = user_id.strip()
    if not uid:
        return "Anonymous"
    if uid.startswith("+") or uid.isdigit():
        # Mask phone number e.g. +919876543210 -> +91****3210
        if len(uid) > 6:
            return uid[:3] + "****" + uid[-4:]
        return "****"
    if len(uid) > 12:
        return uid[:4] + "..." + uid[-4:]
    return uid


def record_call(
    call_id: str,
    user_id: str,
    started_at: str,
    ended_at: str,
    duration_seconds: int,
    outcome: str,
    success_reason: str | None = None,
    failure_reason: str | None = None,
    human_escalation: bool = False,
    emergency_case: bool = False,
) -> dict:
    """Record a completed call record into the SQLite database.

    outcome MUST be either 'successful' or 'failed'.
    """
    valid_outcomes = {"successful", "failed"}
    normalized_outcome = outcome.strip().lower()
    if normalized_outcome not in valid_outcomes:
        raise ValueError(
            f"Invalid call outcome {outcome!r}. Must be one of {valid_outcomes}"
        )

    now = datetime.now(timezone.utc).isoformat()
    clean_uid = user_id.strip().lower()
    dur = max(0, int(duration_seconds))

    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO calls (
                call_id, user_id, started_at, ended_at, duration_seconds,
                outcome, success_reason, failure_reason, human_escalation,
                emergency_case, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(call_id) DO UPDATE SET
                ended_at         = excluded.ended_at,
                duration_seconds = excluded.duration_seconds,
                outcome          = excluded.outcome,
                success_reason   = excluded.success_reason,
                failure_reason   = excluded.failure_reason,
                human_escalation = excluded.human_escalation,
                emergency_case   = excluded.emergency_case
            """,
            (
                call_id.strip(),
                clean_uid,
                started_at,
                ended_at,
                dur,
                normalized_outcome,
                success_reason,
                failure_reason,
                1 if human_escalation else 0,
                1 if emergency_case else 0,
                now,
            ),
        )

    logger.info(
        "Recorded call call_id=%r outcome=%r duration=%ds",
        call_id,
        normalized_outcome,
        dur,
    )

    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM calls WHERE call_id = ?", (call_id.strip(),)
        ).fetchone()
        return dict(row)


def list_calls(limit: int = 50) -> list[dict]:
    """Return recent calls ordered newest first."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM calls ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_analytics_summary() -> dict:
    """Calculate and return real call analytics summary metrics from database.

    Never returns hardcoded demo values. Safely handles 0 calls without division by zero.
    """
    with _get_conn() as conn:
        total_calls = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        successful_calls = conn.execute(
            "SELECT COUNT(*) FROM calls WHERE outcome = 'successful'"
        ).fetchone()[0]
        failed_calls = conn.execute(
            "SELECT COUNT(*) FROM calls WHERE outcome = 'failed'"
        ).fetchone()[0]

        # Calculate success rate safely
        if total_calls > 0:
            raw_rate = (successful_calls / total_calls) * 100.0
            success_rate = round(raw_rate, 1)
            if success_rate.is_integer():
                success_rate = int(success_rate)
        else:
            success_rate = 0

        # Calculate average duration safely
        avg_dur_row = conn.execute(
            "SELECT AVG(duration_seconds) FROM calls"
        ).fetchone()[0]
        avg_duration_seconds = round(avg_dur_row) if avg_dur_row is not None else 0

        human_escalations = conn.execute(
            "SELECT COUNT(*) FROM calls WHERE human_escalation = 1"
        ).fetchone()[0]
        emergency_cases = conn.execute(
            "SELECT COUNT(*) FROM calls WHERE emergency_case = 1"
        ).fetchone()[0]

        # Fetch recent calls with safe metadata only
        recent_rows = conn.execute(
            """
            SELECT call_id, user_id, started_at, duration_seconds, outcome, human_escalation, emergency_case
            FROM calls
            ORDER BY created_at DESC
            LIMIT 20
            """
        ).fetchall()

    recent_calls = []
    for r in recent_rows:
        row_dict = dict(r)
        recent_calls.append(
            {
                "call_id": row_dict["call_id"],
                "user_id_masked": mask_user_id(row_dict["user_id"]),
                "started_at": row_dict["started_at"],
                "duration_seconds": row_dict["duration_seconds"],
                "duration_formatted": format_duration(row_dict["duration_seconds"]),
                "outcome": row_dict["outcome"],
                "human_escalation": bool(row_dict["human_escalation"]),
                "emergency_case": bool(row_dict["emergency_case"]),
            }
        )

    return {
        "total_calls": total_calls,
        "successful_calls": successful_calls,
        "failed_calls": failed_calls,
        "success_rate": success_rate,
        "average_duration_seconds": avg_duration_seconds,
        "average_duration_formatted": format_duration(avg_duration_seconds),
        "human_escalations": human_escalations,
        "emergency_cases": emergency_cases,
        "recent_calls": recent_calls,
    }
