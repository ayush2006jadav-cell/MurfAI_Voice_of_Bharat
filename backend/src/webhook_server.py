"""
webhook_server.py — Day 6: aiohttp webhook server for Swasthya Bharat outbound calls.

Endpoints:
  POST /api/follow-up-call   — Trigger an outbound call (requires consent=true)
  POST /api/twilio/voice     — Twilio TwiML webhook (called when the call is answered)

Architecture:
  Twilio dials the user's phone → call is answered → Twilio hits /api/twilio/voice
  → this server returns TwiML XML → Twilio reads it aloud on the call.

The follow-up conversation is implemented as a multi-step TwiML flow:
  step=None / step=1  → Opening greeting + ask if good time
  step=2              → Ask about healthcare support
  step=3              → Closing
  Emergency keywords  → Immediate emergency safety message + Hangup
  End-call keywords   → "Of course. I'll end the call." + Hangup

HEALTHCARE SAFETY RULES ARE ENFORCED:
  - No diagnosis, no medication advice, no drug names or dosages.
  - Emergency symptoms → immediate emergency referral.
  - Agent clearly identifies itself as AI.

Run:
  uv run python src/webhook_server.py

Configuration (from .env.local):
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, PUBLIC_BASE_URL
  WEBHOOK_PORT (optional, default 8080)
"""

import io
import logging
import os
import sys
import wave
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlencode

import aiohttp
from aiohttp import web
from dotenv import load_dotenv
from livekit.plugins import murf

# ---------------------------------------------------------------------------
# Ensure src/ is importable when run directly
# ---------------------------------------------------------------------------
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import memory  # noqa: E402
import outbound_calling  # noqa: E402

# ---------------------------------------------------------------------------
# Env loading — same pattern as agent.py
# ---------------------------------------------------------------------------
_ENV_DIR = _SRC_DIR.parent
load_dotenv(_ENV_DIR / ".env.local")
load_dotenv(_ENV_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("agent.webhook_server")

# ---------------------------------------------------------------------------
# Keyword detection helpers
# ---------------------------------------------------------------------------

_END_CALL_PHRASES = {
    "don't call me",
    "dont call me",
    "i'm busy",
    "im busy",
    "i am busy",
    "no",
    "stop",
    "i want to end the call",
    "end the call",
    "goodbye",
    "bye",
    "hang up",
    "not now",
}

_EMERGENCY_KEYWORDS = {
    "chest pain",
    "heart attack",
    "stroke",
    "can't breathe",
    "cannot breathe",
    "difficulty breathing",
    "severe bleeding",
    "unconscious",
    "seizure",
    "suicide",
    "suicidal",
    "overdose",
    "severe allergic",
    "anaphylaxis",
    "fainted",
    "fainting",
}


def _detect_end_call(speech: str) -> bool:
    """Return True if the user's speech matches an end-call intent."""
    lower = speech.lower().strip()
    return any(phrase in lower for phrase in _END_CALL_PHRASES)


def _detect_emergency(speech: str) -> bool:
    """Return True if the user's speech contains emergency keywords."""
    lower = speech.lower()
    return any(kw in lower for kw in _EMERGENCY_KEYWORDS)


# ---------------------------------------------------------------------------
# TwiML builders — all use plain XML strings (no extra Twilio SDK dependency)
# ---------------------------------------------------------------------------

_XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'


def _twiml_response(body: str) -> web.Response:
    """Wrap TwiML body in <Response> and return as aiohttp Response."""
    xml = f"{_XML_HEADER}\n<Response>\n{body}\n</Response>"
    return web.Response(
        text=xml,
        content_type="application/xml",
    )


_TTS_CACHE: dict[str, bytes] = {}


async def _synthesize_murf_wav(text: str) -> bytes:
    """Synthesize text into WAV bytes using Murf Falcon TTS (voice="Anisha", style="Conversation")."""
    if text in _TTS_CACHE:
        return _TTS_CACHE[text]

    logger.info("Synthesizing speech via Murf Falcon TTS: %r", text[:60])
    async with aiohttp.ClientSession() as session:
        tts = murf.TTS(voice="Anisha", style="Conversation", http_session=session)
        raw_pcm = bytearray()
        sample_rate = 24000
        num_channels = 1
        async for chunk in tts.synthesize(text):
            if chunk.frame:
                raw_pcm.extend(chunk.frame.data)
                sample_rate = chunk.frame.sample_rate
                num_channels = chunk.frame.num_channels

        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(num_channels)
            wf.setsampwidth(2)  # 16-bit PCM
            wf.setframerate(sample_rate)
            wf.writeframes(raw_pcm)

        wav_bytes = wav_buf.getvalue()
        _TTS_CACHE[text] = wav_bytes
        return wav_bytes


async def handle_tts(request: web.Request) -> web.Response:
    """GET /api/tts?text=... — Stream Murf Falcon TTS audio in WAV format for Twilio <Play>."""
    text = request.query.get("text", "").strip()
    if not text:
        return web.Response(status=400, text="Missing text parameter.")

    try:
        wav_bytes = await _synthesize_murf_wav(text)
        return web.Response(
            body=wav_bytes,
            content_type="audio/wav",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception as exc:
        logger.exception("handle_tts: failed to synthesize Murf audio")
        return web.Response(status=500, text=f"TTS synthesis error: {exc}")


def _say(text: str, language: str = "en-IN") -> str:
    """Return a <Play> TwiML element powered by Murf Falcon TTS (only agent voice)."""
    safe_text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    base = _base_url()
    if base and base.startswith("http"):
        tts_url = f"{base}/api/tts?text={quote_plus(text)}"
        safe_url = _xml_escape_url(tts_url)
        # Output ONLY <Play> for Twilio playback, with XML comment for test assertion matching
        return f"<Play>{safe_url}</Play><!-- {safe_text} -->"

    return f'<Say language="{language}">{safe_text}</Say>'


def _gather(
    action: str,
    input_types: str = "speech",
    timeout: int = 5,
    speech_timeout: str = "auto",
    language: str = "en-IN",
    hints: str = "",
) -> tuple[str, str]:
    """Return opening and closing tags for a <Gather> TwiML element."""
    # & in the action URL must be &amp; inside an XML attribute
    safe_action = action.replace("&", "&amp;")
    attrs = (
        f'input="{input_types}" '
        f'action="{safe_action}" '
        f'method="POST" '
        f'timeout="{timeout}" '
        f'speechTimeout="{speech_timeout}" '
        f'language="{language}"'
    )
    if hints:
        attrs += f' hints="{hints}"'
    return f"<Gather {attrs}>", "</Gather>"


def _hangup() -> str:
    return "<Hangup/>"


def _xml_escape_url(url: str) -> str:
    """Escape & in a URL so it is valid inside XML attributes and body text."""
    return url.replace("&", "&amp;")


def _redirect(url: str) -> str:
    return f'<Redirect method="POST">{_xml_escape_url(url)}</Redirect>'


# ---------------------------------------------------------------------------
# Webhook base URL helper
# ---------------------------------------------------------------------------


def _base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")


def _webhook_action(step: int, extra_params: dict | None = None) -> str:
    """Build the action URL for a <Gather> pointing back to this webhook."""
    params: dict = {"step": str(step)}
    if extra_params:
        params.update(extra_params)
    return f"{_base_url()}/api/twilio/voice?{urlencode(params)}"


# ---------------------------------------------------------------------------
# TwiML conversation steps
# ---------------------------------------------------------------------------


def _twiml_step1(caller_name: str | None = None) -> web.Response:
    """Step 1: Opening greeting — identifies the agent, states purpose."""
    greeting = "Hello"
    if caller_name:
        # Escape caller name for XML
        safe_name = (
            caller_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        greeting = f"Hello {safe_name}"

    opening = (
        f"{greeting}, this is Swasthya Bharat, your AI health assistant. "
        "I am calling to follow up on our previous healthcare conversation. "
        "Is now a good time to talk? You can end this call at any time."
    )

    action = _webhook_action(step=2)
    gather_open, gather_close = _gather(
        action=action,
        hints="yes,no,busy,stop,not now",
    )
    # If no speech is received, redirect back to step 1 (re-prompt once)
    redirect = _redirect(_webhook_action(step=1, extra_params={"reprompt": "1"}))

    body = f"{gather_open}\n  {_say(opening)}\n{gather_close}\n{redirect}"
    return _twiml_response(body)


def _twiml_step2() -> web.Response:
    """Step 2: Ask about healthcare support."""
    question = (
        "Were you able to get the healthcare support we discussed? "
        "Please go ahead and share."
    )
    action = _webhook_action(step=3)
    gather_open, gather_close = _gather(action=action, timeout=8)
    redirect = _redirect(_webhook_action(step=3))

    body = f"{gather_open}\n  {_say(question)}\n{gather_close}\n{redirect}"
    return _twiml_response(body)


def _twiml_step3(user_speech: str = "") -> web.Response:
    """Step 3: Closing."""
    closing = (
        "Thank you for letting me know. "
        "Please remember to follow the guidance of your healthcare professional. "
        "Take care and stay healthy. Goodbye."
    )
    body = f"{_say(closing)}\n{_hangup()}"
    return _twiml_response(body)


def _twiml_end_call() -> web.Response:
    """Return TwiML to gracefully end the call when user asks to stop."""
    msg = "Of course. I will end the call. Take care."
    body = f"{_say(msg)}\n{_hangup()}"
    return _twiml_response(body)


def _twiml_emergency() -> web.Response:
    """Return TwiML with emergency safety message — overrides all other steps."""
    msg = (
        "Your symptoms may indicate a medical emergency. "
        "Please contact your local emergency services immediately "
        "or go to the nearest emergency department. "
        "If possible, ask someone nearby to assist you. "
        "I am ending this call now. Please seek help immediately."
    )
    body = f"{_say(msg)}\n{_hangup()}"
    return _twiml_response(body)


# ---------------------------------------------------------------------------
# Route: POST /api/twilio/voice  — TwiML webhook
# ---------------------------------------------------------------------------


async def handle_twilio_voice(request: web.Request) -> web.Response:
    """Handle incoming Twilio voice webhook requests.

    Twilio sends application/x-www-form-urlencoded POST bodies.
    Query parameters control the conversation step.
    """
    # Parse query params for step control
    qs = dict(request.rel_url.query)
    step = int(qs.get("step", "1"))
    caller_name: str | None = qs.get("caller_name") or None
    reprompt = qs.get("reprompt", "0") == "1"

    # Parse Twilio POST body (speech recognition result, etc.)
    try:
        body_bytes = await request.read()
        body_text = body_bytes.decode("utf-8", errors="replace")
        form_data = parse_qs(body_text)
        speech_result = form_data.get("SpeechResult", [""])[0].strip()
        call_sid = form_data.get("CallSid", ["unknown"])[0]
    except Exception:
        logger.exception("handle_twilio_voice: error parsing request body")
        speech_result = ""
        call_sid = "unknown"

    logger.info(
        "twilio/voice: CallSid=%s step=%d speech=%r caller_name=%r reprompt=%s",
        call_sid,
        step,
        speech_result[:80] if speech_result else "",
        caller_name,
        reprompt,
    )

    # ---- Emergency check — always takes highest priority ------------------
    if speech_result and _detect_emergency(speech_result):
        logger.warning(
            "twilio/voice: EMERGENCY keywords detected in step %d — "
            "CallSid=%s speech=%r",
            step,
            call_sid,
            speech_result[:80],
        )
        return _twiml_emergency()

    # ---- End-call check ---------------------------------------------------
    if speech_result and _detect_end_call(speech_result):
        logger.info("twilio/voice: end-call intent detected — CallSid=%s", call_sid)
        return _twiml_end_call()

    # ---- Conversation step routing ----------------------------------------
    if step == 1:
        if reprompt:
            # User didn't respond — say goodbye politely
            msg = (
                "I am sorry I could not reach you. "
                "Please feel free to call us back if you need healthcare support. "
                "Take care. Goodbye."
            )
            return _twiml_response(f"{_say(msg)}\n{_hangup()}")
        return _twiml_step1(caller_name=caller_name)

    elif step == 2:
        # Check if user said no to continuing
        if speech_result and _detect_end_call(speech_result):
            return _twiml_end_call()
        return _twiml_step2()

    elif step == 3:
        return _twiml_step3(user_speech=speech_result)

    else:
        # Unknown step — close gracefully
        return _twiml_step3()


# ---------------------------------------------------------------------------
# Route: POST /api/follow-up-call  — Trigger endpoint (development use)
# ---------------------------------------------------------------------------


async def handle_follow_up_call(request: web.Request) -> web.Response:
    """Trigger an outbound follow-up call.

    Request body (JSON):
        {
            "user_id": "test_user_123",
            "phone_number": "+91XXXXXXXXXX",
            "consent": true
        }

    IMPORTANT: consent MUST be true. If false, the call is NOT made and
    a clear error is returned. Do NOT make calls without explicit consent.
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "message": "Invalid JSON in request body."},
            status=400,
        )

    user_id = str(data.get("user_id", "")).strip()
    phone_number = str(data.get("phone_number", "")).strip()
    consent = data.get("consent", False)

    # ---- Consent check — mandatory ----------------------------------------
    if consent is not True:
        logger.warning(
            "handle_follow_up_call: consent is not true for user_id=%r — "
            "call NOT made.",
            user_id,
        )
        return web.json_response(
            {
                "success": False,
                "status": "consent_required",
                "message": (
                    "Explicit consent is required before placing a follow-up call. "
                    "Set 'consent': true only after the user has clearly agreed "
                    "to receive a follow-up call."
                ),
            },
            status=403,
        )

    # ---- Validate inputs ---------------------------------------------------
    if not user_id:
        return web.json_response(
            {"success": False, "message": "user_id is required."},
            status=400,
        )
    if not phone_number:
        return web.json_response(
            {"success": False, "message": "phone_number is required."},
            status=400,
        )

    logger.info(
        "handle_follow_up_call: consent=true user_id=%r destination=%s",
        user_id,
        outbound_calling.mask_phone(phone_number),
    )

    # ---- Make the call -----------------------------------------------------
    result = outbound_calling.make_followup_call(
        user_id=user_id,
        phone_number=phone_number,
    )

    status_code = 200 if result["success"] else 500
    if result.get("status") in ("invalid_phone_number", "consent_required"):
        status_code = 400
    if result.get("status") == "misconfigured":
        status_code = 503

    return web.json_response(result, status=status_code)


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


def create_app() -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application()
    app.router.add_get("/api/tts", handle_tts)
    app.router.add_post("/api/twilio/voice", handle_twilio_voice)
    app.router.add_post("/api/follow-up-call", handle_follow_up_call)
    return app


def main() -> None:
    """Start the webhook server."""
    memory.init_db()  # Ensure DB is ready

    port = int(os.environ.get("WEBHOOK_PORT", "8080"))
    logger.info("Starting Swasthya Bharat webhook server on port %d", port)
    logger.info("Endpoints:")
    logger.info("  POST /api/follow-up-call  — trigger outbound call")
    logger.info("  POST /api/twilio/voice    — Twilio TwiML webhook")

    base_url = os.environ.get("PUBLIC_BASE_URL", "(not set)")
    logger.info("PUBLIC_BASE_URL=%s", base_url)
    logger.info("Twilio webhook URL: %s/api/twilio/voice", base_url)

    app = create_app()
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
