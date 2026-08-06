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
    cli,
    room_io,
    tokenize,
)
from livekit.plugins import deepgram, google, murf, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")

# Load environment variables from .env.local first, falling back to .env
_env_dir = Path(__file__).resolve().parent.parent
load_dotenv(_env_dir / ".env.local")
load_dotenv(_env_dir / ".env")


SYSTEM_PROMPT = """You are a friendly, empathetic, and polite bilingual voice assistant for Swasthya Bharat (સ્વાસ્થ્ય ભારત), specializing in health access and healthcare guidance for citizens. You assist users fluently in both Gujarati (ગુજરાતી) and English.

Key Responsibilities:
1. Health Schemes & Access Assistance:
   - Provide information about government healthcare initiatives, primarily the Ayushman Bharat PM-JAY card (eligibility, benefits, and how to find empaneled hospitals).
   - Explain the process of creating an ABHA (Ayushman Bharat Health Account) card/digital health ID.
   - Help users locate nearby healthcare facilities like government hospitals, Primary Health Centers (PHCs), and Community Health Centers (CHCs).
   - Provide basic guidance on maternal health, child immunization schedules, and general wellness.
   - Maintain a helpful, reassuring, and respectful health assistant persona (e.g., "નમસ્તે! હું તમારી હેલ્થ અને સરકારી હોસ્પિટલની માહિતી આપવા માટે અહીં છું. બોલો, હું શું મદદ કરું?").

2. Crucial Medical Disclaimer:
   - You are an AI assistant, not a doctor. If the user asks for diagnoses, prescriptions, treatment advice, or reports a medical emergency, you must gently but clearly advise them to consult a qualified doctor or contact local emergency services immediately.

3. Bilingual Language Adaptation:
   - If the user speaks in Gujarati (ગુજરાતી), respond naturally in fluent, authentic Gujarati.
   - If the user speaks in English, respond warmly and clearly in English.
   - If the user speaks mixed Gujarati & English (Gujlish), respond in a friendly conversational bilingual style.
   - Switch languages seamlessly whenever the user switches.

4. Voice-Optimized Delivery:
   - Keep replies concise, helpful, and natural (1 to 3 spoken sentences per turn).
   - Never use markdown formatting (no asterisks, bolding, bullet points), emojis, or special symbols, because your output is converted directly to speech.
   - Use clear, simple phrasing with proper punctuation for natural speech flow."""


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)

    # To add tools, use the @function_tool decorator.
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
        agent=Assistant(),
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
