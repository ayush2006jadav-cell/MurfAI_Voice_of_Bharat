"""
outbound_calling.py — Day 6: Consent-based outbound follow-up calling for Swasthya Bharat.

Implements make_followup_call(user_id, phone_number) which:
  1. Validates the destination phone number (E.164 format).
  2. Looks up existing caller memory (to optionally greet by name).
  3. Builds the Twilio webhook URL from PUBLIC_BASE_URL env var.
  4. Creates an outbound Twilio call.
  5. Returns call SID and status, or a clear error.

Credentials are read from environment variables — NEVER hard-coded:
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_PHONE_NUMBER
  PUBLIC_BASE_URL

Healthcare safety rules apply during the call (enforced inside webhook_server.py).
Phone numbers are masked in logs: +91******1111
"""

import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv

import memory

# ---------------------------------------------------------------------------
# Env loading — reuse the same pattern as agent.py
# ---------------------------------------------------------------------------
_ENV_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_ENV_DIR / ".env.local")
load_dotenv(_ENV_DIR / ".env")

logger = logging.getLogger("agent.outbound_calling")

# ---------------------------------------------------------------------------
# Phone masking for privacy-safe logging
# ---------------------------------------------------------------------------
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def mask_phone(number: str) -> str:
    """Mask a phone number for log output.

    Example: +919876541111  →  +91******1111
    """
    if not number or len(number) < 8:
        return "****"
    # Keep country code prefix (up to 3 chars after '+') and last 4 digits
    prefix = number[:3]
    suffix = number[-4:]
    middle = "*" * (len(number) - len(prefix) - 4)
    return prefix + middle + suffix


# ---------------------------------------------------------------------------
# Phone validation
# ---------------------------------------------------------------------------


def validate_phone_number(number: str) -> tuple[bool, str]:
    """Return (True, "") if number is valid E.164, else (False, reason).

    E.164 format: starts with '+', 7-15 digits total.
    """
    if not number or not isinstance(number, str):
        return False, "Phone number must be a non-empty string."
    number = number.strip()
    if not _E164_RE.match(number):
        return False, (
            f"Phone number {number!r} is not in valid E.164 format "
            "(e.g. +919876541234 or +17372212163)."
        )
    return True, ""


# ---------------------------------------------------------------------------
# Twilio client — lazy initialised, credentials from env
# ---------------------------------------------------------------------------


def _get_twilio_client():
    """Return a twilio.rest.Client, or raise RuntimeError if credentials are missing."""
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()

    if not account_sid:
        raise RuntimeError(
            "TWILIO_ACCOUNT_SID is not set. "
            "Add it to backend/.env.local and restart the server."
        )
    if not auth_token:
        raise RuntimeError(
            "TWILIO_AUTH_TOKEN is not set. "
            "Add it to backend/.env.local and restart the server."
        )
    # Import here so the module can be imported even without twilio installed
    # (e.g., in unit tests that only test validation logic)
    try:
        from twilio.rest import Client  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "The 'twilio' package is not installed. Run: uv sync"
        ) from exc

    return Client(account_sid, auth_token)


# ---------------------------------------------------------------------------
# Main outbound calling function
# ---------------------------------------------------------------------------


def make_followup_call(user_id: str, phone_number: str) -> dict:
    """Initiate a consent-based follow-up call to *phone_number* for *user_id*.

    Returns a dict with keys:
        success   (bool)
        status    (str)   — Twilio call status or error category
        call_sid  (str)   — Twilio call SID if created, else ""
        message   (str)   — human-readable result
        masked_to (str)   — masked destination number for logging

    This function MUST only be called after explicit user consent (consent==True).
    The caller is responsible for consent verification before invoking this.
    """
    masked = mask_phone(phone_number)
    logger.info("make_followup_call: user_id=%r destination=%s", user_id, masked)

    # ---- 1. Validate phone number ----------------------------------------
    ok, reason = validate_phone_number(phone_number)
    if not ok:
        logger.warning("make_followup_call: invalid phone number — %s", reason)
        return {
            "success": False,
            "status": "invalid_phone_number",
            "call_sid": "",
            "message": f"I wasn't able to place the follow-up call right now. {reason}",
            "masked_to": masked,
        }

    # ---- 2. Check PUBLIC_BASE_URL -----------------------------------------
    base_url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base_url or base_url == "https://example.ngrok-free.app":
        logger.error(
            "make_followup_call: PUBLIC_BASE_URL is not configured. "
            "Set it to your ngrok URL in .env.local."
        )
        return {
            "success": False,
            "status": "misconfigured",
            "call_sid": "",
            "message": (
                "I wasn't able to place the follow-up call right now. "
                "The webhook URL (PUBLIC_BASE_URL) is not configured. "
                "Please set it to your ngrok URL and restart the webhook server."
            ),
            "masked_to": masked,
        }

    webhook_url = f"{base_url}/api/twilio/voice"

    # ---- 3. Caller memory (optional greeting by name) ----------------------
    caller_name: str | None = None
    try:
        record = memory.lookup_caller(user_id)
        if record:
            caller_name = record.get("name")
            logger.info(
                "make_followup_call: found caller name=%r for user_id=%r",
                caller_name,
                user_id,
            )
    except Exception:
        logger.exception(
            "make_followup_call: non-critical error looking up caller memory"
        )

    # ---- 4. Get Twilio credentials ----------------------------------------
    from_number = os.environ.get("TWILIO_PHONE_NUMBER", "").strip()
    if not from_number:
        return {
            "success": False,
            "status": "missing_credentials",
            "call_sid": "",
            "message": (
                "I wasn't able to place the follow-up call right now. "
                "TWILIO_PHONE_NUMBER is not configured."
            ),
            "masked_to": masked,
        }

    # ---- 5. Create the outbound call via Twilio REST API -------------------
    try:
        client = _get_twilio_client()
    except RuntimeError as exc:
        logger.error("make_followup_call: Twilio client error — %s", exc)
        return {
            "success": False,
            "status": "missing_credentials",
            "call_sid": "",
            "message": f"I wasn't able to place the follow-up call right now. {exc}",
            "masked_to": masked,
        }

    # Pass caller_name as a URL parameter so the TwiML webhook can personalise
    # the greeting without storing it separately.
    greeting_url = webhook_url
    if caller_name:
        import urllib.parse

        greeting_url = (
            webhook_url + "?" + urllib.parse.urlencode({"caller_name": caller_name})
        )

    try:
        call = client.calls.create(
            to=phone_number,
            from_=from_number,
            url=greeting_url,
            # status_callback is optional; set if you want async status updates
            # status_callback=f"{base_url}/api/twilio/status",
        )
    except Exception as exc:
        # Covers TwilioRestException, network errors, timeouts, etc.
        error_msg = str(exc)
        logger.error(
            "make_followup_call: Twilio API error for %s — %s", masked, error_msg
        )
        return {
            "success": False,
            "status": "twilio_api_error",
            "call_sid": "",
            "message": (
                "I wasn't able to place the follow-up call right now. "
                f"Twilio error: {error_msg}"
            ),
            "masked_to": masked,
        }

    logger.info(
        "make_followup_call: call created — SID=%r status=%r destination=%s",
        call.sid,
        call.status,
        masked,
    )
    return {
        "success": True,
        "status": call.status,  # e.g. "queued", "initiated"
        "call_sid": call.sid,
        "message": (
            f"Follow-up call initiated successfully. "
            f"Twilio call SID: {call.sid}, status: {call.status}."
        ),
        "masked_to": masked,
    }
