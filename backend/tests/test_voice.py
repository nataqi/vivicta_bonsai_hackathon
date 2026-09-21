import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

from fastapi import HTTPException

import app.post_meeting as post_meeting
import app.voice as voice
from app.coaching import CoachingArea, CompletedMeetingData


def advisor_meeting() -> CompletedMeetingData:
    turns = (
        {
            "id": "c1",
            "speaker": "customer",
            "text": "CUSTOMER SECRET",
            "startTimeMs": 0,
            "endTimeMs": 2_000,
            "durationMs": 2_000,
            "isFinal": True,
        },
        {
            "id": "a1",
            "speaker": "advisor",
            "text": "Let's look at repayment options.",
            "startTimeMs": 2_500,
            "endTimeMs": 5_000,
            "durationMs": 2_500,
            "isFinal": True,
        },
    )
    return CompletedMeetingData(
        turns=turns,
        selected_focus=(CoachingArea.STAY_BEFORE_SOLVING,),
        events=(),
        nudges=(),
    )


def key_moment(turn_id: str = "a1") -> post_meeting.KeyMoment:
    return post_meeting.KeyMoment(
        turn_id=turn_id,
        area=CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
        kind="improvement",
        customer_context="The customer shared a worry.",
        better_answer="That sounds really stressful. Tell me more about it.",
        why="It names the feeling before moving on.",
    )


def report_json(moment: post_meeting.KeyMoment | None) -> str:
    return post_meeting.InternalReport(
        strengths=["A strength."],
        improvements=["An improvement."],
        focus_summary="A focus.",
        takeaway="A takeaway.",
        reflection_context="A bounded context.",
        strength_areas=[CoachingArea.OPEN_QUESTIONS],
        improvement_areas=[CoachingArea.STAY_BEFORE_SOLVING],
        key_moment=moment,
    ).model_dump_json()


class FixedCompletions:
    def __init__(self, content: str) -> None:
        self.content = content

    async def create(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def ai_returning(content: str) -> post_meeting.PostMeetingAI:
    client = SimpleNamespace(chat=SimpleNamespace(completions=FixedCompletions(content)))
    return post_meeting.PostMeetingAI(client)


class FakeProvider:
    def __init__(self, fail_clone: bool = False, fail_delete: bool = False) -> None:
        self.fail_clone = fail_clone
        self.fail_delete = fail_delete
        self.cloned: list[str] = []
        self.spoken: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    async def clone_voice(self, name: str, sample_wav: bytes) -> str:
        if self.fail_clone:
            raise voice.VoiceProviderError("clone failed")
        self.cloned.append(name)
        return "cloned-voice"

    async def speak(self, voice_id: str, text: str) -> bytes:
        self.spoken.append((voice_id, text))
        return b"mp3-bytes"

    async def delete_voice(self, voice_id: str) -> None:
        if self.fail_delete:
            raise voice.VoiceProviderError("delete failed")
        self.deleted.append(voice_id)


def request_with(sample: bytes) -> SimpleNamespace:
    async def body() -> bytes:
        return sample

    return SimpleNamespace(headers={"content-length": str(len(sample))}, body=body)


LONG_SAMPLE = b"\0" * voice.MIN_SAMPLE_BYTES
SHORT_SAMPLE = b"\0" * 1_000


class KeyMomentReportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        post_meeting.store.clear()
        self.previous_ai = post_meeting._ai_service

    def tearDown(self) -> None:
        post_meeting.store.clear()
        post_meeting._ai_service = self.previous_ai

    async def test_report_returns_key_moment_with_turn_times(self) -> None:
        post_meeting._ai_service = ai_returning(report_json(key_moment()))
        session_id = str(uuid4())
        post_meeting.store.register(session_id, advisor_meeting())
        response = await post_meeting.create_report(session_id)
        self.assertIsNotNone(response.key_moment)
        self.assertEqual(response.key_moment.start_time_ms, 2_500)
        self.assertEqual(response.key_moment.end_time_ms, 5_000)
        self.assertNotIn("CUSTOMER SECRET", response.model_dump_json())

    async def test_key_moment_pointing_at_customer_or_unknown_turn_is_dropped(self) -> None:
        for turn_id in ("c1", "missing"):
            post_meeting._ai_service = ai_returning(report_json(key_moment(turn_id)))
            session_id = str(uuid4())
            post_meeting.store.register(session_id, advisor_meeting())
            response = await post_meeting.create_report(session_id)
            self.assertIsNone(response.key_moment)

    async def test_overlong_key_moment_text_is_bounded(self) -> None:
        payload = json.loads(report_json(key_moment()))
        payload["key_moment"]["why"] = "It names the feeling first. " * 20
        post_meeting._ai_service = ai_returning(json.dumps(payload))
        session_id = str(uuid4())
        post_meeting.store.register(session_id, advisor_meeting())
        response = await post_meeting.create_report(session_id)
        self.assertLessEqual(len(response.key_moment.why), 160)


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        post_meeting.store.clear()
        self.previous_provider = voice._provider
        self.provider = FakeProvider()
        voice._provider = self.provider
        self.session_id = str(uuid4())
        self.session = post_meeting.store.register(self.session_id, advisor_meeting())
        self.session.key_moment = key_moment()

    def tearDown(self) -> None:
        post_meeting.store.clear()
        voice._provider = self.previous_provider

    async def settle(self) -> None:
        await asyncio.gather(*tuple(voice._background_tasks))

    async def test_long_sample_is_cloned_and_spoken_from_stored_text(self) -> None:
        response = await voice.better_take(self.session_id, request_with(LONG_SAMPLE))
        self.assertEqual(response.headers["X-Voice-Mode"], "cloned")
        self.assertEqual(self.session.voice_id, "cloned-voice")
        self.assertEqual(self.provider.spoken, [("cloned-voice", key_moment().better_answer)])

    async def test_short_sample_uses_neutral_voice_without_cloning(self) -> None:
        response = await voice.better_take(self.session_id, request_with(SHORT_SAMPLE))
        self.assertEqual(response.headers["X-Voice-Mode"], "neutral")
        self.assertEqual(self.provider.cloned, [])
        self.assertIsNone(self.session.voice_id)

    async def test_clone_failure_falls_back_to_neutral_voice(self) -> None:
        self.provider.fail_clone = True
        response = await voice.better_take(self.session_id, request_with(LONG_SAMPLE))
        self.assertEqual(response.headers["X-Voice-Mode"], "neutral")
        self.assertEqual(self.provider.spoken[0][0], voice.neutral_voice_id())

    async def test_second_request_reuses_cloned_voice(self) -> None:
        await voice.better_take(self.session_id, request_with(LONG_SAMPLE))
        await voice.better_take(self.session_id, request_with(b""))
        self.assertEqual(len(self.provider.cloned), 1)

    async def test_requires_key_moment_and_configured_provider(self) -> None:
        self.session.key_moment = None
        with self.assertRaises(HTTPException) as no_moment:
            await voice.better_take(self.session_id, request_with(LONG_SAMPLE))
        self.assertEqual(no_moment.exception.status_code, 409)
        self.session.key_moment = key_moment()
        voice._provider = None
        with mock.patch.dict("os.environ", {"ELEVENLABS_API_KEY": ""}):
            with self.assertRaises(HTTPException) as no_provider:
                await voice.better_take(self.session_id, request_with(LONG_SAMPLE))
        self.assertEqual(no_provider.exception.status_code, 503)

    async def test_oversized_sample_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as too_large:
            await voice.better_take(
                self.session_id, request_with(b"\0" * (voice.MAX_SAMPLE_BYTES + 1))
            )
        self.assertEqual(too_large.exception.status_code, 413)
        self.assertEqual(self.provider.cloned, [])

    async def test_explicit_delete_confirms_and_clears_voice(self) -> None:
        await voice.better_take(self.session_id, request_with(LONG_SAMPLE))
        result = await voice.delete_voice(self.session_id)
        self.assertEqual(result, {"hadVoice": True, "voiceDeleted": True})
        self.assertEqual(self.provider.deleted, ["cloned-voice"])
        self.assertIsNone(self.session.voice_id)

    async def test_explicit_delete_reports_failure_and_keeps_voice_for_retry(self) -> None:
        await voice.better_take(self.session_id, request_with(LONG_SAMPLE))
        self.provider.fail_delete = True
        result = await voice.delete_voice(self.session_id)
        self.assertEqual(result, {"hadVoice": True, "voiceDeleted": False})
        self.assertEqual(self.session.voice_id, "cloned-voice")

    async def test_delete_without_voice_is_confirmed(self) -> None:
        result = await voice.delete_voice(self.session_id)
        self.assertEqual(result, {"hadVoice": False, "voiceDeleted": True})

    async def test_every_cleanup_path_deletes_provider_voice(self) -> None:
        async def clone_for_new_session() -> tuple[str, post_meeting.PostMeetingSession]:
            session_id = str(uuid4())
            session = post_meeting.store.register(session_id, advisor_meeting())
            session.key_moment = key_moment()
            await voice.better_take(session_id, request_with(LONG_SAMPLE))
            return session_id, session

        session_id, _ = await clone_for_new_session()
        await post_meeting.delete_post_meeting(session_id)
        await self.settle()
        self.assertEqual(self.provider.deleted, ["cloned-voice"])

        self.provider.deleted.clear()
        _, expiring = await clone_for_new_session()
        expiring.expires_at = 0
        post_meeting.store.get("unrelated")
        await self.settle()
        self.assertEqual(self.provider.deleted, ["cloned-voice"])

        self.provider.deleted.clear()
        await clone_for_new_session()
        post_meeting.store.clear()
        await self.settle()
        self.assertEqual(self.provider.deleted, ["cloned-voice"])


if __name__ == "__main__":
    unittest.main()
