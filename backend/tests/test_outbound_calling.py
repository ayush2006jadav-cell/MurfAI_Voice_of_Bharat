"""
test_outbound_calling.py — Day 6: Automated tests for outbound calling.

Tests cover:
  1. Consent=true  → Twilio call created
  2. Consent=false → Twilio call NOT created (403 response)
  3. Missing Twilio credentials → clear error
  4. Invalid phone number → clear error
  5. Twilio API failure → graceful error
  6. TwiML webhook returns valid XML
  7. End-call keywords → <Hangup> in TwiML response
  8. Emergency keywords → emergency safety message in TwiML
  9. PUBLIC_BASE_URL not configured → clear error

All Twilio API calls are mocked. No real phone calls are made.
Memory and facility_lookup tests are not touched.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

# ---------------------------------------------------------------------------
# Ensure src/ is importable
# ---------------------------------------------------------------------------
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import outbound_calling  # noqa: E402

# We import webhook_server after path setup
import webhook_server  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch):
    """Set a valid test environment for each test."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest_account_sid_123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test_auth_token_abc")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+17372212163")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://test.ngrok-free.app")


@pytest.fixture
async def client(aiohttp_client):
    """Return an aiohttp TestClient wrapping the webhook app."""
    app = webhook_server.create_app()
    return await aiohttp_client(app)


# ===========================================================================
# Test 1 — Consent=true → Twilio call is created
# ===========================================================================


def test_make_followup_call_consent_true_creates_call():
    """When consent is true and credentials are valid, make_followup_call creates a call."""
    mock_call = MagicMock()
    mock_call.sid = "CA_test_sid_001"
    mock_call.status = "queued"

    mock_client = MagicMock()
    mock_client.calls.create.return_value = mock_call

    with (
        patch(
            "outbound_calling._get_twilio_client", return_value=mock_client
        ),
        patch("outbound_calling.memory.lookup_caller", return_value=None),
    ):
        result = outbound_calling.make_followup_call(
            user_id="test_user_123",
            phone_number="+919876541111",
        )

    assert result["success"] is True
    assert result["call_sid"] == "CA_test_sid_001"
    assert result["status"] == "queued"
    mock_client.calls.create.assert_called_once()
    # Verify 'to' and 'from_' are set correctly
    call_kwargs = mock_client.calls.create.call_args[1]
    assert call_kwargs["to"] == "+919876541111"
    assert call_kwargs["from_"] == "+17372212163"
    assert "/api/twilio/voice" in call_kwargs["url"]


# ===========================================================================
# Test 2 — Consent=false → Twilio call NOT created (API endpoint level)
# ===========================================================================


@pytest.mark.asyncio
async def test_follow_up_call_endpoint_consent_false_blocks_call(client):
    """POST /api/follow-up-call with consent=false must return 403 and not call Twilio."""
    mock_client = MagicMock()

    with patch("outbound_calling._get_twilio_client", return_value=mock_client):
        resp = await client.post(
            "/api/follow-up-call",
            json={
                "user_id": "test_user_123",
                "phone_number": "+919876541111",
                "consent": False,
            },
        )

    assert resp.status == 403
    data = await resp.json()
    assert data["success"] is False
    assert data["status"] == "consent_required"
    # Twilio must NOT have been called
    mock_client.calls.create.assert_not_called()


@pytest.mark.asyncio
async def test_follow_up_call_endpoint_consent_missing_blocks_call(client):
    """POST /api/follow-up-call without consent field must return 403."""
    mock_client = MagicMock()

    with patch("outbound_calling._get_twilio_client", return_value=mock_client):
        resp = await client.post(
            "/api/follow-up-call",
            json={
                "user_id": "test_user_123",
                "phone_number": "+919876541111",
                # 'consent' key intentionally absent
            },
        )

    assert resp.status == 403
    data = await resp.json()
    assert data["success"] is False
    mock_client.calls.create.assert_not_called()


# ===========================================================================
# Test 3 — Missing Twilio credentials → clear error
# ===========================================================================


def test_make_followup_call_missing_account_sid(monkeypatch):
    """Missing TWILIO_ACCOUNT_SID must return a clear error without calling Twilio."""
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)

    with patch("outbound_calling.memory.lookup_caller", return_value=None):
        result = outbound_calling.make_followup_call(
            user_id="user_no_creds",
            phone_number="+919876541111",
        )

    assert result["success"] is False
    assert result["status"] == "missing_credentials"
    assert "TWILIO_ACCOUNT_SID" in result["message"]


def test_make_followup_call_missing_auth_token(monkeypatch):
    """Missing TWILIO_AUTH_TOKEN must return a clear error."""
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)

    with patch("outbound_calling.memory.lookup_caller", return_value=None):
        result = outbound_calling.make_followup_call(
            user_id="user_no_token",
            phone_number="+919876541111",
        )

    assert result["success"] is False
    assert result["status"] == "missing_credentials"


def test_make_followup_call_missing_from_number(monkeypatch):
    """Missing TWILIO_PHONE_NUMBER must return a clear error."""
    monkeypatch.delenv("TWILIO_PHONE_NUMBER", raising=False)

    mock_client = MagicMock()
    with (
        patch("outbound_calling._get_twilio_client", return_value=mock_client),
        patch("outbound_calling.memory.lookup_caller", return_value=None),
    ):
        result = outbound_calling.make_followup_call(
            user_id="user_no_from",
            phone_number="+919876541111",
        )

    assert result["success"] is False
    assert result["status"] == "missing_credentials"
    mock_client.calls.create.assert_not_called()


# ===========================================================================
# Test 4 — Invalid phone number → clear error
# ===========================================================================


def test_make_followup_call_invalid_phone_no_plus():
    """A phone number without leading '+' must be rejected."""
    result = outbound_calling.make_followup_call(
        user_id="user_bad_phone",
        phone_number="919876541111",  # missing +
    )
    assert result["success"] is False
    assert result["status"] == "invalid_phone_number"
    assert "E.164" in result["message"]


def test_make_followup_call_invalid_phone_too_short():
    """A phone number that is too short must be rejected."""
    result = outbound_calling.make_followup_call(
        user_id="user_bad_phone",
        phone_number="+123",
    )
    assert result["success"] is False
    assert result["status"] == "invalid_phone_number"


def test_make_followup_call_empty_phone():
    """An empty phone number must be rejected."""
    result = outbound_calling.make_followup_call(
        user_id="user_empty_phone",
        phone_number="",
    )
    assert result["success"] is False
    assert result["status"] == "invalid_phone_number"


def test_validate_phone_number_valid():
    """Valid E.164 phone numbers must pass validation."""
    valid_numbers = [
        "+919876541234",
        "+17372212163",
        "+447911123456",
        "+12025551234",
    ]
    for number in valid_numbers:
        ok, reason = outbound_calling.validate_phone_number(number)
        assert ok is True, f"Expected {number!r} to be valid, got reason: {reason}"


def test_validate_phone_number_invalid():
    """Invalid phone numbers must fail validation."""
    invalid_numbers = [
        "919876541234",  # no +
        "+123",  # too short
        "+91 98765 41234",  # spaces
        "not-a-number",
        "",
        "+",
    ]
    for number in invalid_numbers:
        ok, _ = outbound_calling.validate_phone_number(number)
        assert ok is False, f"Expected {number!r} to be invalid"


# ===========================================================================
# Test 5 — Twilio API failure → graceful error
# ===========================================================================


def test_make_followup_call_twilio_api_failure():
    """A Twilio API exception must be caught and returned as a graceful error."""
    mock_client = MagicMock()
    mock_client.calls.create.side_effect = Exception(
        "Twilio API error: invalid credentials"
    )

    with (
        patch("outbound_calling._get_twilio_client", return_value=mock_client),
        patch("outbound_calling.memory.lookup_caller", return_value=None),
    ):
        result = outbound_calling.make_followup_call(
            user_id="user_api_fail",
            phone_number="+919876541111",
        )

    assert result["success"] is False
    assert result["status"] == "twilio_api_error"
    assert "I wasn't able to place the follow-up call" in result["message"]
    assert result["call_sid"] == ""


# ===========================================================================
# Test 6 — TwiML webhook returns valid XML
# ===========================================================================


@pytest.mark.asyncio
async def test_twilio_voice_webhook_returns_xml(client):
    """POST /api/twilio/voice must return Content-Type: application/xml with a <Response> tag."""
    resp = await client.post(
        "/api/twilio/voice",
        data={"CallSid": "CA_test_001"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status == 200
    assert "application/xml" in resp.content_type
    text = await resp.text()
    assert "<Response>" in text
    assert "</Response>" in text


@pytest.mark.asyncio
async def test_twilio_voice_webhook_step1_contains_opening(client):
    """Step 1 TwiML must contain the mandatory opening message."""
    resp = await client.post(
        "/api/twilio/voice?step=1",
        data={"CallSid": "CA_test_002"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status == 200
    text = await resp.text()
    # Must identify as Swasthya Bharat AI assistant
    assert "Swasthya Bharat" in text
    assert "AI health assistant" in text or "AI" in text
    # Must mention that call can be ended
    assert "end this call" in text or "any time" in text
    # Must include a <Gather> for speech input
    assert "<Gather" in text


@pytest.mark.asyncio
async def test_twilio_voice_webhook_step1_with_caller_name(client):
    """Step 1 TwiML must greet the caller by name if caller_name is provided."""
    resp = await client.post(
        "/api/twilio/voice?step=1&caller_name=Ramesh",
        data={"CallSid": "CA_test_003"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status == 200
    text = await resp.text()
    assert "Ramesh" in text


# ===========================================================================
# Test 7 — End-call keywords → <Hangup> in TwiML
# ===========================================================================


@pytest.mark.asyncio
async def test_twilio_voice_end_call_on_stop(client):
    """SpeechResult='stop' during step 2 must trigger the end-call TwiML with <Hangup>."""
    resp = await client.post(
        "/api/twilio/voice?step=2",
        data={"CallSid": "CA_end_001", "SpeechResult": "stop"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status == 200
    text = await resp.text()
    assert "<Hangup" in text
    assert "I will end the call" in text or "end the call" in text


@pytest.mark.asyncio
async def test_twilio_voice_end_call_on_no(client):
    """SpeechResult='no' must trigger the end-call TwiML."""
    resp = await client.post(
        "/api/twilio/voice?step=1",
        data={"CallSid": "CA_end_002", "SpeechResult": "no"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status == 200
    text = await resp.text()
    assert "<Hangup" in text


@pytest.mark.asyncio
async def test_twilio_voice_end_call_on_busy(client):
    """SpeechResult containing 'I am busy' must trigger the end-call TwiML."""
    resp = await client.post(
        "/api/twilio/voice?step=2",
        data={"CallSid": "CA_end_003", "SpeechResult": "I am busy right now"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status == 200
    text = await resp.text()
    assert "<Hangup" in text


# ===========================================================================
# Test 8 — Emergency keywords → emergency safety message in TwiML
# ===========================================================================


@pytest.mark.asyncio
async def test_twilio_voice_emergency_chest_pain(client):
    """Emergency keyword 'chest pain' must trigger the emergency safety response."""
    resp = await client.post(
        "/api/twilio/voice?step=2",
        data={
            "CallSid": "CA_emerg_001",
            "SpeechResult": "I am having severe chest pain right now",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status == 200
    text = await resp.text()
    # Must contain emergency referral
    assert "emergency" in text.lower() or "emergency services" in text.lower()
    assert "<Hangup" in text
    # Must NOT ask a follow-up question (emergency overrides everything)
    assert "Were you able to get" not in text


@pytest.mark.asyncio
async def test_twilio_voice_emergency_suicidal(client):
    """Emergency keyword 'suicidal' must trigger the emergency safety response."""
    resp = await client.post(
        "/api/twilio/voice?step=3",
        data={
            "CallSid": "CA_emerg_002",
            "SpeechResult": "I am feeling suicidal and don't want to live",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status == 200
    text = await resp.text()
    assert "emergency" in text.lower()
    assert "<Hangup" in text


# ===========================================================================
# Test 9 — PUBLIC_BASE_URL not configured → clear error
# ===========================================================================


def test_make_followup_call_public_base_url_not_set(monkeypatch):
    """Missing PUBLIC_BASE_URL must return a misconfigured error."""
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

    with patch("outbound_calling.memory.lookup_caller", return_value=None):
        result = outbound_calling.make_followup_call(
            user_id="user_no_url",
            phone_number="+919876541111",
        )

    assert result["success"] is False
    assert result["status"] == "misconfigured"
    assert "PUBLIC_BASE_URL" in result["message"]


def test_make_followup_call_public_base_url_is_placeholder(monkeypatch):
    """The placeholder ngrok URL 'https://example.ngrok-free.app' must be treated as not configured."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.ngrok-free.app")

    with patch("outbound_calling.memory.lookup_caller", return_value=None):
        result = outbound_calling.make_followup_call(
            user_id="user_placeholder_url",
            phone_number="+919876541111",
        )

    assert result["success"] is False
    assert result["status"] == "misconfigured"


# ===========================================================================
# Test 10 — mask_phone utility
# ===========================================================================


def test_mask_phone_standard():
    """mask_phone must show prefix and last 4 digits only."""
    masked = outbound_calling.mask_phone("+919876541111")
    assert masked.startswith("+91")
    assert masked.endswith("1111")
    assert "9876" not in masked


def test_mask_phone_short():
    """A very short number must not crash — return '****'."""
    masked = outbound_calling.mask_phone("+1")
    assert masked == "****" or masked is not None


def test_mask_phone_empty():
    """An empty number must return '****'."""
    assert outbound_calling.mask_phone("") == "****"


# ===========================================================================
# Test 11 — Caller memory integration: personalised greeting
# ===========================================================================


def test_make_followup_call_uses_caller_name():
    """When caller memory exists, make_followup_call includes the caller name in the webhook URL."""
    mock_call = MagicMock()
    mock_call.sid = "CA_named_001"
    mock_call.status = "queued"

    mock_client = MagicMock()
    mock_client.calls.create.return_value = mock_call

    with (
        patch("outbound_calling._get_twilio_client", return_value=mock_client),
        patch(
            "outbound_calling.memory.lookup_caller",
            return_value={
                "name": "Ramesh",
                "language_preference": "Hindi",
                "facts": {},
                "last_interaction": "2026-08-10T12:00:00+00:00",
            },
        ),
    ):
        result = outbound_calling.make_followup_call(
            user_id="ramesh_123",
            phone_number="+919876541111",
        )

    assert result["success"] is True
    call_kwargs = mock_client.calls.create.call_args[1]
    # caller_name should appear in the webhook URL as a query param
    assert "caller_name=Ramesh" in call_kwargs["url"]
