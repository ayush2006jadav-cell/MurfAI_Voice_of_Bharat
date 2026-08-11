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
