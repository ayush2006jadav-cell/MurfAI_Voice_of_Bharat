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
"""


def init_db() -> None:
    """Create the database and callers table if they do not already exist.

    Call this once at agent startup (inside my_agent).
    """
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute(_CREATE_TABLE_SQL)
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
    merged_lang = language_preference if language_preference is not None else (existing or {}).get("language_preference")
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
