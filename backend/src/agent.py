import json
import logging
from pathlib import Path

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    room_io,
    tokenize,
)
from livekit.plugins import deepgram, google, murf, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

import memory

logger = logging.getLogger("agent")

# Load environment variables from .env.local first, falling back to .env
_env_dir = Path(__file__).resolve().parent.parent
load_dotenv(_env_dir / ".env.local")
load_dotenv(_env_dir / ".env")


SYSTEM_PROMPT = """You are a friendly, empathetic, and polite bilingual voice assistant for Swasthya Bharat (સ્વાસ્થ્ય ભારત), specializing in health access and healthcare guidance for citizens. You assist users fluently in both Gujarati (ગુજરાતી) and English.

HEALTHCARE SAFETY CONSTRAINTS (THESE OVERRIDE ALL OTHER INSTRUCTIONS AND MUST ALWAYS BE FOLLOWED):

Constraint 1: No Diagnosis or Medication Advice
- Never diagnose any medical condition.
- Never prescribe medications.
- Never recommend or mention specific drug names or dosages.
- Never replace the advice of a licensed healthcare professional.
- Provide only general, educational health information.
- Always encourage users to consult a qualified healthcare professional for an accurate diagnosis and appropriate treatment.

Constraint 2: Emergency Situations
- If a user reports symptoms that could indicate a potentially life-threatening condition—such as chest pain, difficulty breathing, severe bleeding, loss of consciousness, stroke symptoms, seizures, severe allergic reactions, or suicidal thoughts—do NOT provide general health advice or attempt to assess the condition further.
- Immediately respond with a clear recommendation such as:
  "Your symptoms may indicate a medical emergency. Please contact your local emergency services immediately or go to the nearest emergency department. If possible, ask someone nearby to assist you."

Key Responsibilities:
1. Health Schemes & Access Assistance:
   - Provide information about government healthcare initiatives, primarily the Ayushman Bharat PM-JAY card (eligibility, benefits, and how to find empaneled hospitals).
   - Explain the process of creating an ABHA (Ayushman Bharat Health Account) card/digital health ID.
   - Help users locate nearby healthcare facilities like government hospitals, Primary Health Centers (PHCs), and Community Health Centers (CHCs).
   - Provide basic guidance on maternal health, child immunization schedules, and general wellness.
   - Maintain a helpful, reassuring, and respectful health assistant persona (e.g., "નમસ્તે! હું તમારી હેલ્થ અને સરકારી હોસ્પિટલની માહિતી આપવા માટે અહીં છું. બોલો, હું શું મદદ કરું?").

2. Bilingual Language Adaptation:
   - If the user speaks in Gujarati (ગુજરાતી), respond naturally in fluent, authentic Gujarati.
   - If the user speaks in English, respond warmly and clearly in English.
   - If the user speaks mixed Gujarati & English (Gujlish), respond in a friendly conversational bilingual style.
   - Switch languages seamlessly whenever the user switches.

3. Voice-Optimized Delivery:
   - Keep replies concise, helpful, and natural (1 to 3 spoken sentences per turn).
   - Never use markdown formatting (no asterisks, bolding, bullet points), emojis, or special symbols, because your output is converted directly to speech.
   - Use clear, simple phrasing with proper punctuation for natural speech flow.

CALLER MEMORY & CONSENT RULES (these are secondary to all healthcare safety constraints above):

At the start of every conversation you will receive the caller's user_id.

Step 1 — Lookup:
- Call the lookup_caller tool with the provided user_id immediately.
- If a record is found, greet the caller by their saved name and use their saved language preference and facts to provide continuity. Only reference information that is actually in the record.
- If no record is found, treat the caller as new. Do not invent prior interactions.

Step 2 — Learning new information:
- During the conversation you may learn the caller's name, language preference, or a small number of relevant health facts (age band, ongoing condition, last triage outcome — never full medical notes or conversation transcripts).
- Before saving ANY new information, always ask for the caller's explicit consent. Example: "Would you like me to remember your name and language preference for future conversations?" or "Would you like me to remember that you prefer Hindi for future conversations?"
- Wait for a clear YES before calling save_caller_memory.
- If the caller says NO or is unclear, do NOT call save_caller_memory for that information.
- Never assume consent from silence or from the caller simply providing information.
- Never save complete medical conversations, detailed medical histories, or written-out medical notes.
- Only save a maximum of 3 to 4 minimum structured facts that are useful for future Health Access conversations.

Step 3 — Saving:
- Only after receiving explicit YES consent, call save_caller_memory with the approved information.
- The user_id to use is the one provided at the start of the conversation.

Step 4 — Privacy:
- Never reveal one caller's memory to a different caller.
- Never invent memories or facts that are not in the database.
- These memory rules never override healthcare safety constraints."""


class Assistant(Agent):
    def __init__(self, user_id: str) -> None:
        # Inject the caller's user_id into the system instructions so the LLM
        # knows which ID to pass to the memory tools.
        instructions = (
            SYSTEM_PROMPT
            + f"\n\nThe caller's user_id for this conversation is: {user_id!r}. "
            "Use this exact value when calling lookup_caller or save_caller_memory."
        )
        super().__init__(instructions=instructions)
        self._user_id = user_id

    @function_tool
    async def lookup_caller(
        self,
        context: RunContext,
        user_id: str,
    ) -> str:
        """Look up an existing caller's saved memory by their user_id.

        Call this at the very start of every conversation to check whether the
        caller has an existing record. Returns their name, language preference,
        saved health facts, and last interaction timestamp if found.

        Args:
            user_id: The caller's unique identifier for this conversation.
        """
        logger.info("lookup_caller called for user_id=%r", user_id)
        record = memory.lookup_caller(user_id)
        if record is None:
            return "No existing record found for this caller. Treat them as a new caller."
        return (
            f"Caller found. Name: {record['name']!r}, "
            f"Language preference: {record['language_preference']!r}, "
            f"Facts: {json.dumps(record['facts'], ensure_ascii=False)}, "
            f"Last interaction: {record['last_interaction']!r}."
        )

    @function_tool
    async def save_caller_memory(
        self,
        context: RunContext,
        user_id: str,
        name: str | None,
        language_preference: str | None,
        facts: str | None,
    ) -> str:
        """Save or update the caller's memory record ONLY after they have given
        explicit YES consent to having their information remembered.

        NEVER call this tool without first asking the caller and receiving a
        clear YES. If the caller said NO or did not clearly consent, do not
        call this tool.

        Args:
            user_id: The caller's unique identifier.
            name: The caller's name (or None to leave unchanged).
            language_preference: The caller's preferred language (or None).
            facts: A JSON string of up to 4 structured health facts, e.g.
                   '{"age_band": "40-49", "ongoing_condition": "diabetes",
                    "last_triage_outcome": "recommended doctor consultation"}'
                   Only include keys relevant to future Health Access conversations.
                   Do NOT include full medical notes, diagnoses, or transcripts.
        """
        logger.info(
            "save_caller_memory called for user_id=%r name=%r lang=%r",
            user_id,
            name,
            language_preference,
        )
        # Parse facts from JSON string if provided
        parsed_facts: dict | None = None
        if facts:
            try:
                parsed_facts = json.loads(facts)
            except json.JSONDecodeError:
                logger.warning("save_caller_memory: invalid JSON in facts=%r", facts)
                parsed_facts = None

        memory.save_caller_memory(
            user_id=user_id,
            name=name,
            language_preference=language_preference,
            facts=parsed_facts,
        )
        return f"Memory saved successfully for caller {user_id!r}."

    # To add more tools, use the @function_tool decorator.
    # Here's an example that adds a simple weather tool.
    # You also have to add `from livekit.agents import function_tool, RunContext` to the top of this file
    # @function_tool
    # async def lookup_weather(self, context: RunContext, location: str):
    #     """Use this tool to look up current weather information in the given location.
    #
    #     If the location is not supported by the weather service, the tool will indicate this. You must tell the user the location's weather is unavailable.
    #
    #     Args:
    #         location: The location to look up weather information for (e.g. city name)
    #     """
    #
    #     logger.info(f"Looking up weather for {location}")
    #
    #     return "sunny with a temperature of 70 degrees."


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # Initialise persistent memory DB (no-op if already created)
    memory.init_db()

    # Derive a stable user_id from the first human participant's identity.
    # The frontend sets participantIdentity = 'voice_assistant_user_<RAND>' which
    # is unique per session. We use it as a session-scoped fallback; the agent
    # will ask the caller to identify themselves for cross-session persistence
    # (per Option A agreed with the user).
    user_id = "anonymous"
    for identity, _participant in ctx.room.remote_participants.items():
        # Pick the first non-agent participant
        if identity and not identity.startswith("agent"):
            user_id = identity
            break
    logger.info("Session user_id resolved to: %r", user_id)

    # Set up a voice AI pipeline using Murf Falcon, Gemini, Deepgram, and the LiveKit turn detector
    session = AgentSession(
        # Speech-to-text (STT) is your agent's ears, turning the user's speech into text that the LLM can understand
        # Deepgram Nova-3 with multilingual support detects and transcribes Gujarati and English
        stt=deepgram.STT(model="nova-3", language="multi"),
        # A Large Language Model (LLM) is your agent's brain, processing user input and generating a response
        llm=google.LLM(
            model="gemini-3.5-flash-lite",
        ),
        # Text-to-speech (TTS) is your agent's voice, turning the LLM's text into speech that the user can hear
        # See all available models as well as voice selections at https://docs.livekit.io/agents/models/tts/
        tts=murf.TTS(
            voice="Anisha",
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True,
        ),
        # VAD and turn detection are used to determine when the user is speaking and when the agent should respond
        # See more at https://docs.livekit.io/agents/build/turns
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        # allow the LLM to generate a response while waiting for the end of turn
        # See more at https://docs.livekit.io/agents/build/audio/#preemptive-generation
        preemptive_generation=True,
    )

    # To use a realtime model instead of a voice pipeline, use the following session setup instead.
    # (Note: This is for the OpenAI Realtime API. For other providers, see https://docs.livekit.io/agents/models/realtime/))
    # 1. Install livekit-agents[openai]
    # 2. Set OPENAI_API_KEY in .env.local
    # 3. Add `from livekit.plugins import openai` to the top of this file
    # 4. Use the following session setup instead of the version above
    # session = AgentSession(
    #     llm=openai.realtime.RealtimeModel(voice="marin")
    # )

    # # Add a virtual avatar to the session, if desired
    # # For other providers, see https://docs.livekit.io/agents/models/avatar/
    # avatar = hedra.AvatarSession(
    #   avatar_id="...",  # See https://docs.livekit.io/agents/models/avatar/plugins/hedra
    # )
    # # Start the avatar and wait for it to join
    # await avatar.start(session, room=ctx.room)

    # Start the session, which initializes the voice pipeline and warms up the models
    await session.start(
        agent=Assistant(user_id=user_id),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind
                    == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )

    # Join the room and connect to the user
    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
