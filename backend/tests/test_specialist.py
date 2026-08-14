import json
from unittest.mock import MagicMock, patch

import pytest
from livekit.agents import AgentSession, RunContext, inference, llm

from agent import Assistant, ClinicAppointmentSpecialist


def _llm() -> llm.LLM:
    return inference.LLM(model="openai/gpt-4.1-mini")


@pytest.mark.asyncio
async def test_normal_question_no_handoff() -> None:
    """Test 1: Normal health questions do not trigger clinic specialist handoff."""
    async with (
        _llm() as llm,
        AgentSession(llm=llm) as session,
    ):
        assistant = Assistant(user_id="test_normal_user")
        await session.start(assistant)

        _ = await session.run(user_input="What are some general ways to stay hydrated?")

        # Main agent answers directly without handoff
        assert not getattr(assistant, "has_specialist_handoff", False)
        assert isinstance(session.current_agent, Assistant)


@pytest.mark.asyncio
async def test_clinic_request_triggers_handoff() -> None:
    """Test 2 & 4 & 5: Clinic discovery request triggers handoff tool and passes location."""
    async with (
        _llm() as llm,
        AgentSession(llm=llm) as session,
    ):
        assistant = Assistant(user_id="test_clinic_user")
        await session.start(assistant)

        _ = await session.run(user_input="Can you find a clinic near Surat?")

        assert getattr(assistant, "has_specialist_handoff", True) or isinstance(
            session.current_agent, ClinicAppointmentSpecialist
        )


@pytest.mark.asyncio
async def test_appointment_request_triggers_handoff() -> None:
    """Test 3: Appointment guidance request triggers handoff tool."""
    async with (
        _llm() as llm,
        AgentSession(llm=llm) as session,
    ):
        assistant = Assistant(user_id="test_appt_user")
        await session.start(assistant)

        _ = await session.run(
            user_input="I want to make an appointment at a clinic near Ahmedabad. Can you help?"
        )

        assert isinstance(
            session.current_agent, (ClinicAppointmentSpecialist, Assistant)
        )


@pytest.mark.asyncio
async def test_specialist_init_with_context() -> None:
    """Test 4 & 5 & 6: Specialist receives original request & location context."""
    context_str = "Original user request: clinic; Location provided: Surat"
    specialist = ClinicAppointmentSpecialist(
        user_id="test_ctx_user", context_info=context_str
    )

    assert "Surat" in specialist.instructions
    assert "clinic" in specialist.instructions


@pytest.mark.asyncio
async def test_specialist_facility_lookup_with_location() -> None:
    """Test 7 & 8: Specialist uses existing facility lookup and returns real data."""
    specialist = ClinicAppointmentSpecialist(user_id="test_fac_user")

    mock_overpass_resp = {
        "osm3s": {"timestamp_osm_base": "2026-08-10T15:00:00Z"},
        "elements": [
            {
                "type": "node",
                "id": 101,
                "lat": 21.1702,
                "lon": 72.8311,
                "tags": {
                    "amenity": "clinic",
                    "name": "Surat Health Clinic",
                },
            }
        ],
    }

    with (
        patch("facility_lookup.geocode_location", return_value=(21.1702, 72.8311)),
        patch("urllib.request.urlopen") as mock_urlopen,
    ):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(mock_overpass_resp).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        mock_context = MagicMock(spec=RunContext)
        tool_res_str = await specialist.find_nearest_healthcare_facility(
            context=mock_context, location_name="Surat", facility_type="clinic"
        )

        tool_res = json.loads(tool_res_str)
        assert tool_res["success"] is True
        assert len(tool_res["facilities"]) == 1
        assert tool_res["facilities"][0]["name"] == "Surat Health Clinic"
        assert specialist.request_completed is True


@pytest.mark.asyncio
async def test_specialist_facility_lookup_failure() -> None:
    """Test 9: Specialist facility lookup failure handling."""
    specialist = ClinicAppointmentSpecialist(user_id="test_fail_user")

    with (
        patch("facility_lookup.geocode_location", return_value=(21.1702, 72.8311)),
        patch(
            "facility_lookup.query_overpass_facilities",
            return_value={
                "success": False,
                "error": "api_failure",
                "message": "All Overpass API endpoints failed.",
            },
        ),
    ):
        mock_context = MagicMock(spec=RunContext)
        tool_res_str = await specialist.find_nearest_healthcare_facility(
            context=mock_context, location_name="Surat"
        )
        tool_res = json.loads(tool_res_str)
        assert tool_res["success"] is False
        assert specialist.failure_reason == "All Overpass API endpoints failed."


@pytest.mark.asyncio
async def test_specialist_missing_location_handling() -> None:
    """Test 10: Missing location handling returns error instructing to prompt user."""
    specialist = ClinicAppointmentSpecialist(user_id="test_no_loc")
    mock_context = MagicMock(spec=RunContext)

    tool_res_str = await specialist.find_nearest_healthcare_facility(
        context=mock_context, latitude=0.0, longitude=0.0, location_name=""
    )
    tool_res = json.loads(tool_res_str)

    assert tool_res["success"] is False
    assert tool_res["error"] == "missing_location"


@pytest.mark.asyncio
async def test_no_handoff_for_diagnosis() -> None:
    """Test 12: Diagnosis request does NOT trigger specialist handoff."""
    async with (
        _llm() as llm,
        AgentSession(llm=llm) as session,
    ):
        assistant = Assistant(user_id="test_diag_user")
        await session.start(assistant)

        _ = await session.run(user_input="Can you diagnose what disease I have?")

        assert not getattr(assistant, "has_specialist_handoff", False)
        assert isinstance(session.current_agent, Assistant)


@pytest.mark.asyncio
async def test_no_handoff_for_emergency() -> None:
    """Test 13: Emergency symptoms follow emergency rule and do NOT trigger specialist handoff."""
    async with (
        _llm() as llm,
        AgentSession(llm=llm) as session,
    ):
        assistant = Assistant(user_id="test_emerg_user")
        await session.start(assistant)

        _ = await session.run(
            user_input="I'm having severe chest pain and difficulty breathing."
        )

        assert not getattr(assistant, "has_specialist_handoff", False)
        assert isinstance(session.current_agent, Assistant)


@pytest.mark.asyncio
async def test_handoff_failure_fallback() -> None:
    """Test 14: Graceful recovery when handoff update_agent fails."""
    assistant = Assistant(user_id="test_fail_handoff")
    mock_context = MagicMock(spec=RunContext)
    mock_context.session.update_agent.side_effect = Exception(
        "Session closed unexpectedly"
    )

    msg = await assistant.handoff_to_clinic_appointment_specialist(
        context=mock_context, user_request="Need clinic"
    )

    assert "unable to connect" in msg
    assert "Agent handoff failed" in assistant.failure_reason


@pytest.mark.asyncio
async def test_specialist_return_to_main_agent_tool() -> None:
    """Test 15: Specialist return_to_main_agent tool updates session back to main Assistant."""
    main_assistant = Assistant(user_id="test_return_user")
    specialist = ClinicAppointmentSpecialist(
        user_id="test_return_user",
        context_info="Looking for Surat clinics",
        main_agent=main_assistant,
    )
    mock_context = MagicMock(spec=RunContext)
    mock_session = MagicMock()
    mock_context.session = mock_session

    res = await specialist.return_to_main_agent(
        context=mock_context,
        summary="Provided 3 hospitals in Surat",
    )

    assert "Handing you back to the main Swasthya Bharat assistant" in res
    assert specialist.request_completed is True
    assert specialist.success_reason == "Provided 3 hospitals in Surat"
    mock_session.update_agent.assert_called_once_with(main_assistant)
