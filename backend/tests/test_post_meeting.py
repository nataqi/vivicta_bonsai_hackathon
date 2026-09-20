import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

import app.post_meeting as post_meeting
from app.openrouter import OPENROUTER_BASE_URL, OPENROUTER_MODEL
from app.coaching import (
    CoachingArea,
    CompletedMeetingData,
    Confidence,
    DetectedEvent,
    EventType,
    LiveNudge,
    NudgeKey,
    TimedWord,
    TurnObservation,
)


def meeting_data(text: str = "I am worried about this.") -> CompletedMeetingData:
    turn = {
        "id": "c1",
        "speaker": "customer",
        "text": text,
        "startTimeMs": 0,
        "endTimeMs": 2_000,
        "durationMs": 2_000,
        "isFinal": True,
    }
    event = DetectedEvent(
        CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
        EventType.CUSTOMER_EMOTIONAL_CUE,
        Confidence.HIGH,
        2_000,
        "The customer expressed concern.",
        ("c1",),
    )
    nudge = LiveNudge(
        CoachingArea.STAY_BEFORE_SOLVING,
        NudgeKey.STAY_BEFORE_SOLVING,
        "Stay with the moment before solving.",
        2_000,
    )
    return CompletedMeetingData(
        turns=(turn,),
        selected_focus=(CoachingArea.STAY_BEFORE_SOLVING,),
        events=(event,),
        nudges=(nudge,),
    )


class CapturingCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        schema_name = kwargs["response_format"]["json_schema"]["name"]
        if schema_name == "internalreport":
            parsed = post_meeting.InternalReport(
                strengths=["You gave the concern room."],
                improvements=["Pause before moving into solutions."],
                focus_summary="Stay with emotional cues before solving.",
                takeaway="Pause, acknowledge, then solve.",
                reflection_context="The adviser can practise acknowledging concerns before solutions.",
            )
        elif schema_name == "reflectionfollowup":
            parsed = post_meeting.ReflectionFollowUp(
                coach_message="What could you try before offering the next step?"
            )
        else:
            parsed = post_meeting.ReflectionCompletion(
                coach_message="That sounds like a useful intention to carry forward.",
                takeaway="Pause and acknowledge before solving.",
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=parsed.model_dump_json()))]
        )


class FixedContentCompletions:
    def __init__(self, content: str) -> None:
        self.content = content

    async def create(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FailingAI:
    async def generate_report(self, snapshot):
        raise post_meeting.PostMeetingAIError("temporary failure")


class BlockingAI:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_report(self, snapshot):
        self.started.set()
        await self.release.wait()
        return post_meeting.InternalReport(
            strengths=["A strength."],
            improvements=["An improvement."],
            focus_summary="A focus.",
            takeaway="A takeaway.",
            reflection_context="A bounded context.",
        )


class PostMeetingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        post_meeting.store.clear()
        self.previous_ai = post_meeting._ai_service

    def tearDown(self) -> None:
        post_meeting.store.clear()
        post_meeting._ai_service = self.previous_ai

    async def test_freeze_detaches_complete_meeting_history(self) -> None:
        from app.coaching import CoachingSession

        session = CoachingSession()
        observation = TurnObservation(
            {
                "id": "a1",
                "speaker": "advisor",
                "text": "Hello",
                "startTimeMs": 0,
                "endTimeMs": 1_000,
                "durationMs": 1_000,
                "isFinal": True,
            },
            (TimedWord("Hello", 0, 500),),
        )
        session.observe(observation)
        frozen = await session.freeze()
        observation.turn["text"] = "mutated"
        self.assertEqual(frozen.turns[0]["text"], "Hello")
        self.assertIsNone(session.observe(observation))
        self.assertEqual(len(frozen.turns), 1)

    async def test_snapshot_contains_focus_events_nudges_and_payload_context(self) -> None:
        session_id = str(uuid4())
        session = post_meeting.store.register(session_id, meeting_data())
        self.assertEqual(session.snapshot.selected_focus, (CoachingArea.STAY_BEFORE_SOLVING,))
        payload = post_meeting.build_report_payload(session.snapshot)
        self.assertEqual(payload["finalizedTurns"][0]["id"], "c1")
        self.assertEqual(len(payload["semanticEvents"]), 1)
        self.assertEqual(payload["displayedNudges"][0]["nudgeKey"], "STAY_BEFORE_SOLVING")

    async def test_structured_report_is_cached_and_validated(self) -> None:
        completions = CapturingCompletions()
        post_meeting._ai_service = post_meeting.PostMeetingAI(
            SimpleNamespace(chat=SimpleNamespace(completions=completions))
        )
        session_id = str(uuid4())
        post_meeting.store.register(session_id, meeting_data())

        first = await post_meeting.create_report(session_id)
        second = await post_meeting.create_report(session_id)

        self.assertEqual(first.report.takeaway, "Pause, acknowledge, then solve.")
        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertEqual(len(completions.calls), 1)
        self.assertEqual(completions.calls[0]["model"], OPENROUTER_MODEL)
        self.assertEqual(completions.calls[0]["max_tokens"], 800)
        self.assertEqual(completions.calls[0]["response_format"]["type"], "json_schema")

    async def test_client_uses_openrouter_key_and_never_falls_back_to_openai(self) -> None:
        with patch.dict(
            "os.environ",
            {"OPENROUTER_API_KEY": "router-key", "OPENAI_API_KEY": "personal-key"},
            clear=True,
        ), patch("app.post_meeting.AsyncOpenAI") as client:
            post_meeting.PostMeetingAI.from_environment()
        client.assert_called_once_with(
            api_key="router-key",
            base_url=OPENROUTER_BASE_URL,
            timeout=12.0,
            max_retries=0,
        )

        with patch.dict("os.environ", {"OPENAI_API_KEY": "personal-key"}, clear=True):
            self.assertIsNone(post_meeting.PostMeetingAI.from_environment().client)

    async def test_report_item_limits_are_enforced(self) -> None:
        with self.assertRaises(ValueError):
            post_meeting.PostMeetingReport(
                strengths=["x" * 181],
                improvements=["A useful improvement."],
                focus_summary="Focus.",
                takeaway="Takeaway.",
            )

    async def test_malformed_report_json_logs_sanitized_validation_metadata(self) -> None:
        post_meeting._ai_service = post_meeting.PostMeetingAI(
            SimpleNamespace(
                chat=SimpleNamespace(
                    completions=FixedContentCompletions("not valid json CUSTOMER SECRET")
                )
            )
        )
        session_id = str(uuid4())
        post_meeting.store.register(session_id, meeting_data())

        with self.assertLogs("app.post_meeting", level="WARNING") as captured:
            with self.assertRaises(HTTPException) as failure:
                await post_meeting.create_report(session_id)

        self.assertEqual(failure.exception.status_code, 503)
        diagnostic = next(
            line
            for line in captured.output
            if "structured output validation failed" in line
        )
        self.assertIn("json_invalid", diagnostic)
        self.assertIn("count=1", diagnostic)
        self.assertNotIn("CUSTOMER SECRET", diagnostic)
        self.assertIsNone(post_meeting.store.get(session_id).report)

    async def test_schema_invalid_report_json_logs_field_metadata_only(self) -> None:
        invalid_report = {
            "strengths": ["A strength."],
            "improvements": ["An improvement."],
            "focus_summary": {"content": "CUSTOMER SECRET"},
            "takeaway": "A takeaway.",
            "reflection_context": "A bounded context.",
        }
        post_meeting._ai_service = post_meeting.PostMeetingAI(
            SimpleNamespace(
                chat=SimpleNamespace(
                    completions=FixedContentCompletions(json.dumps(invalid_report))
                )
            )
        )
        session_id = str(uuid4())
        post_meeting.store.register(session_id, meeting_data())

        with self.assertLogs("app.post_meeting", level="WARNING") as captured:
            with self.assertRaises(HTTPException) as failure:
                await post_meeting.create_report(session_id)

        self.assertEqual(failure.exception.status_code, 503)
        diagnostic = next(
            line
            for line in captured.output
            if "structured output validation failed" in line
        )
        self.assertIn("string_type", diagnostic)
        self.assertIn("focus_summary", diagnostic)
        self.assertIn("count=1", diagnostic)
        self.assertNotIn("CUSTOMER SECRET", diagnostic)
        self.assertIsNone(post_meeting.store.get(session_id).report)

    async def test_overlong_report_text_is_truncated_before_validation(self) -> None:
        overlong_report = {
            "strengths": ["s" * 220],
            "improvements": ["i" * 220],
            "focus_summary": "f" * 260,
            "takeaway": "t" * 200,
            "reflection_context": "r" * 700,
        }
        post_meeting._ai_service = post_meeting.PostMeetingAI(
            SimpleNamespace(
                chat=SimpleNamespace(
                    completions=FixedContentCompletions(json.dumps(overlong_report))
                )
            )
        )
        session_id = str(uuid4())
        post_meeting.store.register(session_id, meeting_data())

        response = await post_meeting.create_report(session_id)

        self.assertEqual(len(response.report.strengths[0]), 180)
        self.assertEqual(len(response.report.improvements[0]), 180)
        self.assertEqual(len(response.report.focus_summary), 220)
        self.assertEqual(len(response.report.takeaway), 160)
        self.assertEqual(len(post_meeting.store.get(session_id).reflection_context), 600)

    async def test_structurally_invalid_report_json_remains_recoverable(self) -> None:
        invalid_report = {
            "strengths": "not a list",
            "improvements": ["An improvement."],
            "focus_summary": "A focus.",
            "takeaway": "A takeaway.",
            "reflection_context": "A bounded context.",
        }
        post_meeting._ai_service = post_meeting.PostMeetingAI(
            SimpleNamespace(
                chat=SimpleNamespace(
                    completions=FixedContentCompletions(json.dumps(invalid_report))
                )
            )
        )
        session_id = str(uuid4())
        post_meeting.store.register(session_id, meeting_data())

        with self.assertRaises(HTTPException) as failure:
            await post_meeting.create_report(session_id)

        self.assertEqual(failure.exception.status_code, 503)
        self.assertIsNone(post_meeting.store.get(session_id).report)

    async def test_unexpected_report_field_remains_recoverable_and_sanitized(self) -> None:
        valid_report_with_extra = {
            "strengths": ["A strength."],
            "improvements": ["An improvement."],
            "focus_summary": "A focus.",
            "takeaway": "A takeaway.",
            "reflection_context": "A bounded context.",
            "unexpected": "CUSTOMER SECRET MODEL CONTENT",
        }
        post_meeting._ai_service = post_meeting.PostMeetingAI(
            SimpleNamespace(
                chat=SimpleNamespace(
                    completions=FixedContentCompletions(json.dumps(valid_report_with_extra))
                )
            )
        )
        session_id = str(uuid4())
        post_meeting.store.register(session_id, meeting_data())

        with self.assertLogs("app.post_meeting", level="WARNING") as captured:
            with self.assertRaises(HTTPException) as failure:
                await post_meeting.create_report(session_id)

        self.assertEqual(failure.exception.status_code, 503)
        diagnostic = next(
            line
            for line in captured.output
            if "structured output validation failed" in line
        )
        self.assertIn("extra_forbidden", diagnostic)
        self.assertIn("unexpected", diagnostic)
        self.assertNotIn("CUSTOMER SECRET MODEL CONTENT", diagnostic)
        self.assertIsNone(post_meeting.store.get(session_id).report)

    async def test_report_failure_remains_retryable(self) -> None:
        post_meeting._ai_service = FailingAI()
        session_id = str(uuid4())
        post_meeting.store.register(session_id, meeting_data())
        with self.assertRaises(HTTPException) as failure:
            await post_meeting.create_report(session_id)
        self.assertEqual(failure.exception.status_code, 503)
        self.assertIsNone(post_meeting.store.get(session_id).report)

    async def test_reflection_is_bounded_idempotent_and_does_not_send_transcript(self) -> None:
        completions = CapturingCompletions()
        post_meeting._ai_service = post_meeting.PostMeetingAI(
            SimpleNamespace(chat=SimpleNamespace(completions=completions))
        )
        session_id = str(uuid4())
        post_meeting.store.register(session_id, meeting_data("CUSTOMER TRANSCRIPT SECRET"))
        await post_meeting.create_report(session_id)

        first_id = uuid4()
        first = await post_meeting.create_reflection(
            session_id,
            post_meeting.ReflectionRequest(message_id=first_id, message="I moved too quickly."),
        )
        duplicate = await post_meeting.create_reflection(
            session_id,
            post_meeting.ReflectionRequest(message_id=first_id, message="I moved too quickly."),
        )
        second = await post_meeting.create_reflection(
            session_id,
            post_meeting.ReflectionRequest(message_id=uuid4(), message="I will pause first."),
        )

        self.assertFalse(first.complete)
        self.assertEqual(first.model_dump(), duplicate.model_dump())
        self.assertTrue(second.complete)
        self.assertTrue(second.takeaway)
        self.assertEqual(post_meeting.store.get(session_id).reflection_reply_count, 2)
        reflection_inputs = [
            call["messages"][-1]["content"]
            for call in completions.calls
            if call["response_format"]["json_schema"]["name"]
            in ("reflectionfollowup", "reflectioncompletion")
        ]
        self.assertTrue(reflection_inputs)
        self.assertTrue(all("CUSTOMER TRANSCRIPT SECRET" not in value for value in reflection_inputs))

        with self.assertRaises(HTTPException) as completed:
            await post_meeting.create_reflection(
                session_id,
                post_meeting.ReflectionRequest(message_id=uuid4(), message="One more thought."),
            )
        self.assertEqual(completed.exception.status_code, 409)

    async def test_delete_is_idempotent_and_late_report_cannot_recreate_session(self) -> None:
        blocking = BlockingAI()
        post_meeting._ai_service = blocking
        session_id = str(uuid4())
        post_meeting.store.register(session_id, meeting_data())
        task = asyncio.create_task(post_meeting.create_report(session_id))
        await blocking.started.wait()
        await post_meeting.delete_post_meeting(session_id)
        await post_meeting.delete_post_meeting(session_id)
        blocking.release.set()
        with self.assertRaises(HTTPException) as deleted:
            await task
        self.assertEqual(deleted.exception.status_code, 410)
        self.assertIsNone(post_meeting.store.get(session_id))


if __name__ == "__main__":
    unittest.main()
