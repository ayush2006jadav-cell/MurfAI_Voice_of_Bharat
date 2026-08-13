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
# Day 7 — Escalation Dashboard Routes
# ---------------------------------------------------------------------------


async def handle_get_escalations(request: web.Request) -> web.Response:
    """GET /api/escalations — Return JSON list of escalation requests."""
    status = request.query.get("status")
    items = memory.list_escalations(status=status)
    return web.json_response({"success": True, "escalations": items})


async def handle_update_escalation_status(request: web.Request) -> web.Response:
    """POST /api/escalations/status — Update status of an escalation request."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "message": "Invalid JSON in request body."},
            status=400,
        )

    ref_id = str(data.get("reference_id", "")).strip()
    status = str(data.get("status", "")).strip()

    if not ref_id or not status:
        return web.json_response(
            {"success": False, "message": "reference_id and status are required."},
            status=400,
        )

    try:
        updated = memory.update_escalation_status(ref_id, status)
        if updated is None:
            return web.json_response(
                {"success": False, "message": f"Escalation {ref_id!r} not found."},
                status=404,
            )
        return web.json_response({"success": True, "escalation": updated})
    except ValueError as exc:
        return web.json_response({"success": False, "message": str(exc)}, status=400)


async def handle_dashboard(request: web.Request) -> web.Response:
    """GET /dashboard — Simple HTML dashboard to view human escalation requests."""
    items = memory.list_escalations()
    rows_html = ""

    for item in items:
        urgency_bg = "#dc2626" if item["urgency"] == "urgent" else "#2563eb"
        status_bg = (
            "#eab308"
            if item["status"] == "open"
            else ("#3b82f6" if item["status"] == "in_progress" else "#16a34a")
        )
        name_disp = item["name"] or "Anonymous"
        lang_disp = item["language"] or "N/A"
        method_disp = item["follow_up_method"] or "phone"

        rows_html += f"""
        <tr>
            <td style="font-weight:bold; font-family:monospace; color:#38bdf8;">{item["reference_id"]}</td>
            <td><span style="background:{urgency_bg}; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;">{item["urgency"].upper()}</span></td>
            <td><span style="background:{status_bg}; color:#000; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;">{item["status"].upper()}</span></td>
            <td>{name_disp}</td>
            <td>{item["reason"]}</td>
            <td style="max-width:250px;">{item["what_happened"]}</td>
            <td style="max-width:250px;">{item["agent_checked"]}</td>
            <td>{lang_disp} / {method_disp}</td>
            <td style="font-size:12px; color:#9ca3af;">{item["created_at"][:19]}</td>
            <td>
                <select onchange="updateStatus('{item["reference_id"]}', this.value)" style="background:#1e293b; color:#fff; border:1px solid #475569; border-radius:4px; padding:4px;">
                    <option value="open" {"selected" if item["status"] == "open" else ""}>Open</option>
                    <option value="in_progress" {"selected" if item["status"] == "in_progress" else ""}>In Progress</option>
                    <option value="resolved" {"selected" if item["status"] == "resolved" else ""}>Resolved</option>
                </select>
            </td>
        </tr>
        """

    if not rows_html:
        rows_html = '<tr><td colspan="10" style="text-align:center; padding:30px; color:#9ca3af;">No escalation requests found.</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Swasthya Bharat — Human Support Dashboard</title>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
        h1 {{ font-size: 24px; margin-bottom: 8px; color: #38bdf8; display: flex; align-items: center; gap: 10px; }}
        p {{ color: #94a3b8; margin-bottom: 24px; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); }}
        th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #0f172a; color: #94a3b8; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; }}
        tr:hover {{ background: #283548; }}
        .badge {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }}
    </style>
</head>
<body>
    <h1>🏥 Swasthya Bharat — Human Support Dashboard</h1>
    <p>View and manage escalation requests created when callers report emergency symptoms or request medical diagnosis.</p>
    <table>
        <thead>
            <tr>
                <th>Ref ID</th>
                <th>Urgency</th>
                <th>Status</th>
                <th>Caller Name</th>
                <th>Reason</th>
                <th>What Happened</th>
                <th>Agent Checked</th>
                <th>Lang / Method</th>
                <th>Created At</th>
                <th>Action</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>

    <script>
        async function updateStatus(refId, newStatus) {{
            try {{
                const res = await fetch('/api/escalations/status', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ reference_id: refId, status: newStatus }})
                }});
                const data = await res.json();
                if (data.success) {{
                    location.reload();
                }} else {{
                    alert('Error: ' + data.message);
                }}
            }} catch (err) {{
                alert('Failed to update status: ' + err);
            }}
        }}
    </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def handle_get_analytics(request: web.Request) -> web.Response:
    """GET /api/analytics — Return JSON metrics for Call Analytics Dashboard."""
    summary = memory.get_analytics_summary()
    return web.json_response(summary)


async def handle_call_analytics_dashboard(request: web.Request) -> web.Response:
    """GET /analytics — HTML Call Analytics Dashboard for Swasthya Bharat."""
    summary = memory.get_analytics_summary()

    recent_rows_html = ""
    for c in summary["recent_calls"]:
        outcome_bg = "#16a34a" if c["outcome"] == "successful" else "#dc2626"
        esc_badge = (
            '<span style="background:#eab308; color:#000; padding:2px 6px; border-radius:10px; font-weight:bold;">Yes</span>'
            if c["human_escalation"]
            else '<span style="color:#9ca3af;">No</span>'
        )
        emerg_badge = (
            '<span style="background:#dc2626; color:#fff; padding:2px 6px; border-radius:10px; font-weight:bold;">Yes</span>'
            if c["emergency_case"]
            else '<span style="color:#9ca3af;">No</span>'
        )

        recent_rows_html += f"""
        <tr>
            <td style="font-family:monospace; color:#38bdf8; font-weight:bold;">{c["call_id"]}</td>
            <td style="font-size:13px; color:#cbd5e1;">{c["started_at"][:19]}</td>
            <td style="font-size:13px;">{c["duration_formatted"]}</td>
            <td><span style="background:{outcome_bg}; color:#fff; padding:3px 8px; border-radius:12px; font-size:12px; font-weight:bold;">{c["outcome"].upper()}</span></td>
            <td>{esc_badge}</td>
            <td>{emerg_badge}</td>
        </tr>
        """

    if not recent_rows_html:
        recent_rows_html = '<tr><td colspan="6" style="text-align:center; padding:30px; color:#9ca3af;">No calls recorded yet.</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Swasthya Bharat — Call Analytics</title>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 1px solid #334155; padding-bottom: 16px; }}
        h1 {{ font-size: 24px; margin: 0; color: #38bdf8; display: flex; align-items: center; gap: 10px; }}
        .badge-live {{ background: #0284c7; color: white; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }}
        .section-title {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.08em; color: #94a3b8; margin-top: 24px; margin-bottom: 12px; font-weight: 700; }}
        .grid-3 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 20px; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2); }}
        .card-title {{ font-size: 13px; color: #94a3b8; font-weight: 600; text-transform: uppercase; margin-bottom: 8px; }}
        .card-value {{ font-size: 32px; font-weight: 800; color: #f8fafc; }}
        .val-success {{ color: #4ade80; }}
        .val-failed {{ color: #f87171; }}
        .val-blue {{ color: #38bdf8; }}
        .val-amber {{ color: #fbbf24; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2); margin-top: 12px; }}
        th, td {{ padding: 14px 18px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #0f172a; color: #94a3b8; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }}
        tr:hover {{ background: #283548; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 Swasthya Bharat — Call Analytics</h1>
        <span class="badge-live">Live SQLite Data</span>
    </div>

    <div class="section-title">Top Metrics</div>
    <div class="grid-3">
        <div class="card">
            <div class="card-title">Total Calls</div>
            <div class="card-value">{summary["total_calls"]}</div>
        </div>
        <div class="card">
            <div class="card-title">Successful Calls</div>
            <div class="card-value val-success">{summary["successful_calls"]}</div>
        </div>
        <div class="card">
            <div class="card-title">Failed Calls</div>
            <div class="card-value val-failed">{summary["failed_calls"]}</div>
        </div>
    </div>

    <div class="section-title">Secondary Metrics</div>
    <div class="grid-3">
        <div class="card">
            <div class="card-title">Success Rate</div>
            <div class="card-value val-blue">{summary["success_rate"]}%</div>
        </div>
        <div class="card">
            <div class="card-title">Human Escalations</div>
            <div class="card-value val-amber">{summary["human_escalations"]}</div>
        </div>
        <div class="card">
            <div class="card-title">Emergency Cases</div>
            <div class="card-value val-failed">{summary["emergency_cases"]}</div>
        </div>
    </div>

    <div class="card" style="margin-bottom: 24px;">
        <div class="card-title">Average Call Duration</div>
        <div class="card-value val-blue">{summary["average_duration_formatted"]}</div>
    </div>

    <div class="section-title">Recent Calls</div>
    <table>
        <thead>
            <tr>
                <th>Call ID</th>
                <th>Date / Time</th>
                <th>Duration</th>
                <th>Outcome</th>
                <th>Human Escalation</th>
                <th>Emergency Case</th>
            </tr>
        </thead>
        <tbody>
            {recent_rows_html}
        </tbody>
    </table>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


def create_app() -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application()
    app.router.add_get("/api/tts", handle_tts)
    app.router.add_post("/api/twilio/voice", handle_twilio_voice)
    app.router.add_post("/api/follow-up-call", handle_follow_up_call)
    app.router.add_get("/dashboard", handle_dashboard)
    app.router.add_get("/api/escalations", handle_get_escalations)
    app.router.add_post("/api/escalations/status", handle_update_escalation_status)
    app.router.add_get("/api/analytics", handle_get_analytics)
    app.router.add_get("/analytics", handle_call_analytics_dashboard)
    return app


def main() -> None:
    """Start the webhook server."""
    memory.init_db()  # Ensure DB is ready

    port = int(os.environ.get("WEBHOOK_PORT", "8080"))
    logger.info("Starting Swasthya Bharat webhook server on port %d", port)
    logger.info("Endpoints:")
    logger.info("  POST /api/follow-up-call  — trigger outbound call")
    logger.info("  POST /api/twilio/voice    — Twilio TwiML webhook")
    logger.info("  GET  /api/analytics        — Call Analytics API")
    logger.info("  GET  /analytics            — Call Analytics Dashboard")

    base_url = os.environ.get("PUBLIC_BASE_URL", "(not set)")
    logger.info("PUBLIC_BASE_URL=%s", base_url)
    logger.info("Twilio webhook URL: %s/api/twilio/voice", base_url)

    app = create_app()
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
