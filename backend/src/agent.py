import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
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

import facility_lookup
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
- These memory rules never override healthcare safety constraints.

- Privacy rule: Never save the user's GPS coordinates, latitude, longitude, or address into persistent caller memory.

HUMAN HELP & ESCALATION RULES (DAY 7):
Create a human-help request ONLY when the caller either reports potentially life-threatening symptoms or explicitly asks for a medical diagnosis, AND ONLY after the caller has explicitly consented to sharing a short summary with a human support team. Do not call create_escalation for normal health questions or without explicit consent.

Situation 1 — Red-flag / Life-threatening Symptoms:
1. ALWAYS give existing emergency safety guidance FIRST (contact emergency services or go to nearest emergency department).
2. AFTER emergency guidance, offer human escalation: "If you would like, I can also send a short summary of this conversation to a human support team. Would you like me to do that?"
3. Explain what will be shared (name, what happened, what was checked, urgency='urgent', language preference).
4. Wait for explicit YES consent before calling create_escalation with urgency="urgent" and reason="emergency_red_flags".
5. If the user says NO, do NOT call create_escalation.

Situation 2 — User Asks for a Medical Diagnosis:
1. Refuse diagnosis immediately ("I cannot diagnose a medical condition. I can provide general health information, or I can ask for human assistance if you'd like.").
2. Ask if they would like human assistance: "Would you like me to send a short summary to a human support team?"
3. Explain what will be shared (name, what happened, what was checked, urgency='normal', language preference).
4. Wait for explicit YES consent before calling create_escalation with urgency="normal" and reason="diagnosis_request".
5. If the user says NO, do NOT call create_escalation.

Mandatory Consent & Privacy Constraints:
- NEVER call create_escalation without receiving an explicit YES from the user.
- If the caller says NO or is silent, do NOT call create_escalation.
- NEVER call create_escalation for general health questions, facility lookups, or normal conversations.
- NEVER store passwords, OTPs, PINs, bank details, API keys, full conversation transcripts, or detailed medical notes in the summary.

SPECIALIST HANDOFF RULES (DAY 9):
Call the handoff_to_clinic_appointment_specialist tool ONLY when the user's request specifically requires healthcare facility discovery (finding clinics, hospitals, doctors' offices, or Primary Health Centers) or general appointment-related guidance.

DO NOT call handoff_to_clinic_appointment_specialist for:
- General health questions or wellness information.
- Symptom questions that can be safely answered with educational guidance.
- Diagnosis requests (refuse and offer human escalation per Rule 2 above).
- Medication questions, drug names, or dosages.
- Emergency situations (follow Emergency Constraint 2 immediately).
- Caller memory lookup/save or normal chat.

When calling handoff_to_clinic_appointment_specialist, pass the user's original request, any city or area already provided (e.g. 'Surat', 'Ahmedabad'), and the requested facility type.
Before transferring, inform the caller clearly: "I'll connect you to our clinic and appointment specialist to help you find a suitable healthcare facility."
"""


SPECIALIST_SYSTEM_PROMPT = """You are the Clinic & Appointment Specialist for Swasthya Bharat (સ્વાસ્થ્ય ભારત). Your job is to help users find suitable healthcare facilities (hospitals, clinics, doctors' offices, and Primary Health Centers) and provide general appointment-related guidance. Use real facility data whenever available using the find_nearest_healthcare_facility tool. Never invent facility details, opening hours, phone numbers, consultation fees, or appointment availability. You do not diagnose medical conditions, prescribe medications, recommend drug names or dosages, or replace professional medical advice. If appointment availability cannot be verified, clearly tell the user and advise them to contact the healthcare facility directly.

Key Responsibilities & Behaviors:
1. Specialist Introduction:
   - When introducing yourself after taking over a conversation, be brief and natural: "Hello, I'm the Clinic & Appointment Specialist. I can help you find nearby healthcare facilities and provide general appointment guidance."
   - Acknowledge any relevant context already provided (such as city/area, facility type, or original user request) so the user does not have to repeat themselves.

2. Real Healthcare Facility Discovery:
   - Use find_nearest_healthcare_facility to search for real facilities via OpenStreetMap.
   - If a location (such as "Surat" or "Ahmedabad") is provided in context or by the user, search using that location directly. Do NOT ask for the location again if it was already provided.
   - If location is missing or unknown, ask: "Which city or area should I search around?"
   - Report factual information returned by the facility lookup tool.
   - If facility lookup fails or returns no results, respond clearly: "I'm unable to retrieve nearby healthcare facilities right now. Please try again later or contact a known healthcare facility directly." Never invent or hallucinate facilities.

3. General Appointment Guidance & Mandatory Limitations:
   - Guide users on how to arrange appointments directly with facilities (e.g., recommend calling the clinic, preparing their name, preferred time slot, general reason for visit, and contact details).
   - CLEARLY explain that you cannot book appointments directly because there is no live appointment booking system integrated.
   - NEVER claim an appointment has been booked or that a doctor has accepted an appointment.
   - NEVER invent appointment slots, doctor availability, clinic timings, consultation fees, contact numbers, or specific healthcare services.
   - Never ask for or collect sensitive personal data such as OTPs, passwords, PINs, bank details, or account numbers.

4. Healthcare & Emergency Safety Constraints (MANDATORY):
   - Never diagnose any medical condition.
   - Never prescribe medications or recommend drug names or dosages.
   - If the user reports potentially life-threatening emergency symptoms (chest pain, difficulty breathing, severe bleeding, etc.), immediately advise them to contact local emergency services (108) or go to the nearest emergency department.

5. Bilingual & Voice-Optimized Delivery:
   - Respond fluently in Gujarati if the user speaks Gujarati, English if English, or bilingual Gujlish if mixed.
   - Keep replies concise (1 to 3 spoken sentences per turn).
   - Do NOT use markdown formatting (no asterisks, bolding, bullet points), emojis, or special symbols.

6. Returning to the Main Agent:
   - After you have completed the user's clinic or appointment request (facility information given, or user says they have what they need, or user asks a general health question), you MUST call the return_to_main_agent tool to hand the conversation back to the main Swasthya Bharat agent.
   - Before calling return_to_main_agent, say something like: "I'll hand you back to the main Swasthya Bharat assistant now. Is there anything else I can help with?"
   - Never answer general health, medication, or symptom questions — politely redirect those to the main agent by calling return_to_main_agent.
"""


class ClinicAppointmentSpecialist(Agent):
    def __init__(
        self,
        user_id: str = "anonymous",
        context_info: str | None = None,
        main_agent: Agent | None = None,
    ) -> None:
        instructions = (
            SPECIALIST_SYSTEM_PROMPT
            + f"\n\nThe caller's user_id for this conversation is: {user_id!r}. "
            "Use this exact value when calling lookup_caller or save_caller_memory."
        )
        if context_info:
            instructions += f"\n\nContext passed from main agent: {context_info}"
        super().__init__(instructions=instructions)
        self._user_id = user_id
        self._main_agent = main_agent
        self.request_completed = False
        self.success_reason: str | None = None
        self.failure_reason: str | None = None
        self.has_human_escalation = False
        self.has_emergency = False

    async def _delayed_intro(self) -> None:
        await asyncio.sleep(0.5)
        if self.session:
            try:
                logger.info("ClinicAppointmentSpecialist speaking introductory message")
                await self.session.say(
                    "Hello, I'm the Clinic and Appointment Specialist for Swasthya Bharat."
                    " I can help you find nearby healthcare facilities and provide general appointment guidance."
                    " Which city or area would you like me to check?",
                    add_to_chat_ctx=True,
                )
            except Exception as exc:
                logger.exception("Failed during specialist intro: %s", exc)

    async def on_enter(self) -> None:
        """Triggered automatically when the session updates the active agent to this specialist."""
        logger.info("ClinicAppointmentSpecialist on_enter triggered")
        self._intro_task = asyncio.create_task(self._delayed_intro())

    @function_tool
    async def lookup_caller(
        self,
        context: RunContext,
        user_id: str,
    ) -> str:
        """Look up an existing caller's saved memory by user_id."""
        logger.info("Specialist lookup_caller called for user_id=%r", user_id)
        record = memory.lookup_caller(user_id)
        if record is None:
            return (
                "No existing record found for this caller. Treat them as a new caller."
            )
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
        """Save or update caller memory after explicit YES consent."""
        logger.info("Specialist save_caller_memory called for user_id=%r", user_id)
        parsed_facts: dict | None = None
        if facts:
            try:
                parsed_facts = json.loads(facts)
            except json.JSONDecodeError:
                parsed_facts = None
        memory.save_caller_memory(
            user_id=user_id,
            name=name,
            language_preference=language_preference,
            facts=parsed_facts,
        )
        return f"Memory saved successfully for caller {user_id!r}."

    @function_tool
    async def find_nearest_healthcare_facility(
        self,
        context: RunContext,
        latitude: float = 0.0,
        longitude: float = 0.0,
        facility_type: str = "any",
        radius_km: float = 10.0,
        limit: int = 3,
        location_name: str | None = None,
    ) -> str:
        """Find real healthcare facilities near the user's location using OpenStreetMap data. Use this tool when the user asks for a nearby hospital, clinic, doctor, health centre, PHC, or healthcare facility. Never invent facility names or locations.

        Args:
            latitude: The user's latitude (e.g. 23.0225). Pass 0.0 if unknown.
            longitude: The user's longitude (e.g. 72.5714). Pass 0.0 if unknown.
            facility_type: Specific facility type ("hospital", "clinic", "doctor", "health_post", or "any").
            radius_km: Search radius in kilometers (default 10.0).
            limit: Maximum number of facilities to return (default 3).
            location_name: City, locality, or place name if lat/lon are not directly available (e.g. "Ahmedabad", "Surat").
        """
        logger.info(
            "Specialist find_nearest_healthcare_facility: lat=%r lon=%r type=%r radius=%r loc=%r",
            latitude,
            longitude,
            facility_type,
            radius_km,
            location_name,
        )

        if latitude == 0.0 and longitude == 0.0:
            if location_name and location_name.strip():
                coords = await asyncio.to_thread(
                    facility_lookup.geocode_location, location_name
                )
                if coords is None:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "location_not_found",
                            "message": f"I couldn't find geographic coordinates for '{location_name}'. Please ask the user to clarify their city or area.",
                        },
                        ensure_ascii=False,
                    )
                latitude, longitude = coords
            else:
                return json.dumps(
                    {
                        "success": False,
                        "error": "missing_location",
                        "message": "I can find nearby healthcare facilities, but I need your current city or location first.",
                    },
                    ensure_ascii=False,
                )

        result = await asyncio.to_thread(
            facility_lookup.query_overpass_facilities,
            latitude=latitude,
            longitude=longitude,
            facility_type=facility_type,
            radius_km=radius_km,
            limit=limit,
        )
        if isinstance(result, dict) and result.get("success"):
            self.request_completed = True
            self.success_reason = "Healthcare facility lookup completed"
        elif isinstance(result, dict) and not result.get("success"):
            self.failure_reason = result.get("message", "Facility lookup failed")

        return json.dumps(result, ensure_ascii=False)

    @function_tool
    async def return_to_main_agent(
        self,
        context: RunContext,
        summary: str = "",
    ) -> str:
        """Hand the conversation back to the main Swasthya Bharat assistant after completing the clinic or appointment task, or when the user asks a general health question outside this specialist's scope.

        Call this tool after you have given the user the facility information they requested, or when the user explicitly says they are done, or when they ask something outside your scope.

        Args:
            summary: A brief one-sentence summary of what was accomplished (e.g. 'Found 3 hospitals near Surat and advised user to call directly for appointment.').
        """
        logger.info(
            "ClinicAppointmentSpecialist return_to_main_agent called: summary=%r", summary
        )
        self.request_completed = True
        if not self.success_reason:
            self.success_reason = summary or "Clinic/appointment task completed"

        target_agent = self._main_agent or Assistant(user_id=self._user_id)
        context.session.update_agent(target_agent)
        return "Handing you back to the main Swasthya Bharat assistant now. Is there anything else about your health I can help with?"


class Assistant(Agent):
    def __init__(self, user_id: str = "anonymous") -> None:
        # Inject the caller's user_id into the system instructions so the LLM
        # knows which ID to pass to the memory tools.
        instructions = (
            SYSTEM_PROMPT
            + f"\n\nThe caller's user_id for this conversation is: {user_id!r}. "
            "Use this exact value when calling lookup_caller or save_caller_memory."
        )
        super().__init__(instructions=instructions)
        self._user_id = user_id
        self.has_human_escalation = False
        self.has_emergency = False
        self.has_specialist_handoff = False
        self.request_completed = False
        self.success_reason: str | None = None
        self.failure_reason: str | None = None

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
            return (
                "No existing record found for this caller. Treat them as a new caller."
            )
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

    @function_tool
    async def find_nearest_healthcare_facility(
        self,
        context: RunContext,
        latitude: float = 0.0,
        longitude: float = 0.0,
        facility_type: str = "any",
        radius_km: float = 10.0,
        limit: int = 3,
        location_name: str | None = None,
    ) -> str:
        """Find real healthcare facilities near the user's current location using OpenStreetMap geographic data. Use this tool when the user asks for a nearby hospital, clinic, doctor, health centre, PHC, healthcare facility, or where they can seek in-person medical care. Do not use this tool for general medical questions that do not require a physical healthcare facility. Never invent facility names or locations. The tool requires the user's latitude and longitude. If location is unavailable, ask the user for their city, area, or location before calling the tool.

        Args:
            latitude: The user's latitude (e.g. 23.0225). Pass 0.0 if unknown.
            longitude: The user's longitude (e.g. 72.5714). Pass 0.0 if unknown.
            facility_type: Specific facility type requested ("hospital", "clinic", "doctor", "health_post", or "any").
            radius_km: Search radius in kilometers (default 10.0).
            limit: Maximum number of facilities to return (default 3).
            location_name: City, locality, or place name if lat/lon are not directly available (e.g. "Ahmedabad", "Surat").
        """
        logger.info(
            "find_nearest_healthcare_facility called: lat=%r lon=%r type=%r radius=%r loc=%r",
            latitude,
            longitude,
            facility_type,
            radius_km,
            location_name,
        )

        if latitude == 0.0 and longitude == 0.0:
            if location_name and location_name.strip():
                coords = await asyncio.to_thread(
                    facility_lookup.geocode_location, location_name
                )
                if coords is None:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "location_not_found",
                            "message": f"I couldn't find geographic coordinates for '{location_name}'. Please ask the user to clarify their city or area.",
                        },
                        ensure_ascii=False,
                    )
                latitude, longitude = coords
            else:
                return json.dumps(
                    {
                        "success": False,
                        "error": "missing_location",
                        "message": "I can find nearby healthcare facilities, but I need your current city or location first.",
                    },
                    ensure_ascii=False,
                )

        result = await asyncio.to_thread(
            facility_lookup.query_overpass_facilities,
            latitude=latitude,
            longitude=longitude,
            facility_type=facility_type,
            radius_km=radius_km,
            limit=limit,
        )
        if isinstance(result, dict) and result.get("success"):
            self.request_completed = True
            self.success_reason = "Healthcare facility lookup completed"
        elif isinstance(result, dict) and not result.get("success"):
            self.failure_reason = result.get("message", "Facility lookup failed")

        return json.dumps(result, ensure_ascii=False)

    @function_tool
    async def create_escalation(
        self,
        context: RunContext,
        user_id: str,
        reason: str,
        what_happened: str,
        agent_checked: str,
        urgency: str = "normal",
        name: str | None = None,
        language: str | None = None,
        follow_up_method: str | None = "phone",
    ) -> str:
        """Create a human-help request when the caller either reports potentially life-threatening symptoms or explicitly asks for a medical diagnosis, but ONLY after the caller has explicitly consented to sharing a short summary with a human support team. Do not call this function for normal health questions or without explicit consent.

        Args:
            user_id: The caller's unique identifier.
            reason: Reason for escalation ("emergency_red_flags" or "diagnosis_request").
            what_happened: Concise description of what caller reported (e.g., "Caller reported chest pain and difficulty breathing").
            agent_checked: Summary of what agent checked/advised (e.g., "Advised emergency services immediately").
            urgency: Urgency level ("urgent" for emergency symptoms, "normal" for diagnosis requests).
            name: Caller's name if provided/consented.
            language: Preferred language (e.g., "Gujarati", "English", "Hindi").
            follow_up_method: Preferred follow-up channel ("phone", "app", etc.).
        """
        logger.info(
            "create_escalation called for user_id=%r reason=%r urgency=%r",
            user_id,
            reason,
            urgency,
        )
        record = memory.create_escalation_record(
            user_id=user_id,
            reason=reason,
            what_happened=what_happened,
            agent_checked=agent_checked,
            urgency=urgency,
            name=name,
            language=language,
            follow_up_method=follow_up_method,
        )
        self.has_human_escalation = True
        if urgency == "urgent" or reason == "emergency_red_flags":
            self.has_emergency = True
        self.request_completed = True
        self.success_reason = "Human escalation request created"

        ref_id = record["reference_id"]
        return (
            f"Escalation request created successfully. "
            f"Reference ID: {ref_id}. Urgency: {record['urgency']}. "
            "Please inform the caller of their Reference ID."
        )

    @function_tool
    async def handoff_to_clinic_appointment_specialist(
        self,
        context: RunContext,
        user_request: str = "",
        location_name: str | None = None,
        facility_type: str = "any",
    ) -> str:
        """Hand off the conversation to the Clinic & Appointment Specialist when the user wants help finding a clinic, hospital, doctor, healthcare facility, or Primary Health Center, or when the user asks for general appointment-related guidance. Use this tool when the request is specifically about healthcare facility discovery or arranging/contacting a facility for an appointment. Do not use this tool for general health questions, diagnosis requests, medication requests, emergencies, or human-help escalation.

        Args:
            user_request: The user's original request or reason for seeking clinic/appointment assistance.
            location_name: The city, locality, or area provided by the user (e.g. "Surat", "Ahmedabad"), or None if not specified.
            facility_type: The type of facility requested ("clinic", "hospital", "doctor", "health_post", or "any").
        """
        logger.info(
            "handoff_to_clinic_appointment_specialist called: request=%r loc=%r type=%r",
            user_request,
            location_name,
            facility_type,
        )

        context_parts = []
        if user_request and user_request.strip():
            context_parts.append(f"Original user request: {user_request.strip()}")
        if location_name and location_name.strip():
            context_parts.append(f"Location provided: {location_name.strip()}")
        if facility_type and facility_type != "any":
            context_parts.append(f"Facility type requested: {facility_type}")

        context_info = "; ".join(context_parts) if context_parts else None

        try:
            specialist = ClinicAppointmentSpecialist(
                user_id=self._user_id,
                context_info=context_info,
                main_agent=self,
            )
            context.session.update_agent(specialist)
            self.request_completed = True
            self.success_reason = "Handed off to Clinic & Appointment Specialist"
            self.has_specialist_handoff = True
            return "I'll connect you to our clinic and appointment specialist to help you find a suitable healthcare facility."
        except Exception as exc:
            logger.exception("Failed to switch agent to specialist: %s", exc)
            self.failure_reason = f"Agent handoff failed: {exc}"
            return "I'm unable to connect you to the clinic and appointment specialist right now. I can still help with general health information."

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
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # Initialise persistent memory DB (no-op if already created)
    memory.init_db()

    # Derive a stable user_id from the first human participant's identity.
    # The frontend sets participantIdentity = 'voice_assistant_user_<RAND>' which
    # is unique per session.
    user_id = "anonymous"
    for identity, _participant in ctx.room.remote_participants.items():
        # Pick the first non-agent participant
        if identity and not identity.startswith("agent"):
            user_id = identity
            break
    logger.info("Session user_id resolved to: %r", user_id)

    # Set up a voice AI pipeline using Murf Falcon, Gemini, Deepgram, and the LiveKit turn detector
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="multi"),
        llm=google.LLM(
            model="gemini-3.5-flash-lite",
        ),
        tts=murf.TTS(
            voice="Anisha",
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    assistant = Assistant(user_id=user_id)
    started_at_dt = datetime.now(timezone.utc)
    started_at = started_at_dt.isoformat()
    call_id = f"CALL-{started_at_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    @session.on("conversation_item_added")
    def _on_item_added(ev):
        item = getattr(ev, "item", None)
        role_str = str(getattr(item, "role", "")).lower()
        if "assistant" in role_str:
            curr_ag = getattr(session, "current_agent", assistant)
            curr_ag.request_completed = True
            if not getattr(curr_ag, "success_reason", None):
                curr_ag.success_reason = "General health guidance provided"
            content = str(getattr(item, "content", "")).lower()
            if (
                "medical emergency" in content
                or "emergency department" in content
                or "emergency services" in content
            ):
                curr_ag.has_emergency = True

    @session.on("agent_state_changed")
    def _on_agent_state(ev):
        new_state_str = str(getattr(ev, "new_state", "")).lower()
        if "speaking" in new_state_str:
            curr_ag = getattr(session, "current_agent", assistant)
            curr_ag.request_completed = True
            if not getattr(curr_ag, "success_reason", None):
                curr_ag.success_reason = "General health guidance provided"

    @session.on("speech_created")
    def _on_speech_created(ev):
        curr_ag = getattr(session, "current_agent", assistant)
        curr_ag.request_completed = True
        if not getattr(curr_ag, "success_reason", None):
            curr_ag.success_reason = "General health guidance provided"

    disconnect_event = asyncio.Event()

    @ctx.room.on("disconnected")
    def _on_disconnected(*args, **kwargs):
        if not disconnect_event.is_set():
            disconnect_event.set()

    try:
        await session.start(
            agent=assistant,
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

        # Connect to the room (joins LiveKit room and enables audio I/O)
        await ctx.connect()

        # Wait until the user or agent disconnects from the room
        await disconnect_event.wait()
    finally:
        ended_at_dt = datetime.now(timezone.utc)
        ended_at = ended_at_dt.isoformat()
        duration_seconds = max(0, int((ended_at_dt - started_at_dt).total_seconds()))

        active_agent = getattr(session, "current_agent", assistant)
        req_completed = getattr(active_agent, "request_completed", False) or getattr(
            assistant, "request_completed", False
        )
        succ_reason = getattr(active_agent, "success_reason", None) or getattr(
            assistant, "success_reason", None
        )
        fail_reason = getattr(active_agent, "failure_reason", None) or getattr(
            assistant, "failure_reason", None
        )
        has_esc = getattr(active_agent, "has_human_escalation", False) or getattr(
            assistant, "has_human_escalation", False
        )
        has_emerg = getattr(active_agent, "has_emergency", False) or getattr(
            assistant, "has_emergency", False
        )

        # Inspect session ground-truth history items for guaranteed success detection
        if (
            not req_completed
            and hasattr(session, "history")
            and hasattr(session.history, "items")
        ):
            for item in session.history.items:
                role_str = str(getattr(item, "role", "")).lower()
                name_str = str(getattr(item, "name", "")).lower()
                content_str = str(getattr(item, "content", "")).lower()

                if "assistant" in role_str:
                    req_completed = True
                    succ_reason = "General health guidance provided"
                    if any(
                        kw in content_str
                        for kw in [
                            "medical emergency",
                            "emergency department",
                            "emergency services",
                            "108",
                        ]
                    ):
                        has_emerg = True
                    break
                if name_str in (
                    "find_nearest_healthcare_facility",
                    "create_escalation",
                    "save_caller_memory",
                    "handoff_to_clinic_appointment_specialist",
                ):
                    req_completed = True
                    succ_reason = f"Request handled via {name_str}"
                    if name_str == "create_escalation":
                        has_esc = True
                    break

        outcome = "successful" if req_completed else "failed"
        final_failure_reason = (
            None
            if req_completed
            else (
                fail_reason
                or "User disconnected or ended conversation before request was completed"
            )
        )

        try:
            memory.record_call(
                call_id=call_id,
                user_id=user_id,
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=duration_seconds,
                outcome=outcome,
                success_reason=succ_reason,
                failure_reason=final_failure_reason,
                human_escalation=has_esc,
                emergency_case=has_emerg,
            )
        except Exception as exc:
            logger.exception("Failed to record call analytics: %s", exc)


if __name__ == "__main__":
    cli.run_app(server)
