import asyncio
import unittest
from types import SimpleNamespace

from app.coaching import (
    CoachingArea,
    CoachingSession,
    Confidence,
    DetectedEvent,
    EventType,
    TimedWord,
    TurnObservation,
)
from app.transcription import (
    ReflectionTranscriptAssembler,
    SpeakerTurnAssembler,
    emit_coached_observation,
)
from app.post_meeting import store as post_meeting_store


def word(
    text: str,
    start: float,
    end: float,
    speaker: int | None,
    punctuated_word: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        word=text,
        punctuated_word=punctuated_word,
        start=start,
        end=end,
        speaker=speaker,
    )


def result(
    words: list[SimpleNamespace],
    *,
    is_final: bool = True,
    speech_final: bool = False,
    from_finalize: bool = False,
) -> SimpleNamespace:
    alternative = SimpleNamespace(
        transcript=" ".join(item.word for item in words),
        words=words,
    )
    return SimpleNamespace(
        is_final=is_final,
        speech_final=speech_final,
        from_finalize=from_finalize,
        channel=SimpleNamespace(alternatives=[alternative]),
    )


class SpeakerTurnAssemblerTests(unittest.TestCase):
    def test_ignores_interim_and_empty_results(self) -> None:
        assembler = SpeakerTurnAssembler()

        interim = result(
            [word("temporary", 0.0, 0.4, 0)],
            is_final=False,
            speech_final=True,
        )
        empty = result([], speech_final=True)

        self.assertEqual(assembler.consume(interim), [])
        self.assertEqual(assembler.consume(empty), [])

    def test_accumulates_final_segments_until_speech_final(self) -> None:
        assembler = SpeakerTurnAssembler()

        first = result([word("hello", 1.0, 1.4, 7, "Hello")])
        second = result(
            [word("there", 1.5, 2.0, 7, "there.")],
            speech_final=True,
        )

        self.assertEqual(assembler.consume(first), [])
        turns = assembler.consume(second)

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["speaker"], "advisor")
        self.assertEqual(turns[0]["text"], "Hello there.")
        self.assertEqual(turns[0]["startTimeMs"], 1000)
        self.assertEqual(turns[0]["endTimeMs"], 2000)
        self.assertEqual(turns[0]["durationMs"], 1000)
        self.assertTrue(turns[0]["isFinal"])

    def test_preview_matches_pending_turn_and_id_carries_to_final_flush(self) -> None:
        assembler = SpeakerTurnAssembler()

        first = result([word("hello", 1.0, 1.4, 7, "Hello")])
        self.assertEqual(assembler.consume(first), [])

        preview = assembler.preview_observation()
        self.assertIsNotNone(preview)
        self.assertFalse(preview.turn["isFinal"])
        self.assertEqual(preview.turn["text"], "Hello")
        self.assertEqual(preview.turn["speaker"], "advisor")

        second = result([word("there", 1.5, 2.0, 7, "there.")], speech_final=True)
        turns = assembler.consume(second)

        self.assertEqual(len(turns), 1)
        self.assertTrue(turns[0]["isFinal"])
        self.assertEqual(turns[0]["id"], preview.turn["id"])
        self.assertIsNone(assembler.preview_observation())

    def test_splits_speaker_changes_and_keeps_mapping(self) -> None:
        assembler = SpeakerTurnAssembler()
        mixed = result(
            [
                word("I", 0.0, 0.2, 4),
                word("understand.", 0.2, 0.8, 4),
                word("Thanks.", 0.9, 1.4, 9),
            ],
            speech_final=True,
        )

        turns = assembler.consume(mixed)

        self.assertEqual([turn["speaker"] for turn in turns], ["advisor", "customer"])
        self.assertEqual([turn["text"] for turn in turns], ["I understand.", "Thanks."])

        later = result([word("Again.", 2.0, 2.5, 4)], speech_final=True)
        self.assertEqual(assembler.consume(later)[0]["speaker"], "advisor")

    def test_finalize_flushes_once(self) -> None:
        assembler = SpeakerTurnAssembler()
        finalized = result(
            [word("last", 0.0, 0.3, 0), word("phrase", 0.3, 0.7, 0)],
            from_finalize=True,
        )

        turns = assembler.consume(finalized)

        self.assertEqual(len(turns), 1)
        self.assertEqual(assembler.flush(), [])

    def test_timeout_flush_keeps_final_observation_for_session_processing(self) -> None:
        assembler = SpeakerTurnAssembler()
        assembler.consume_observations(
            result([word("final", 4.0, 4.4, 0)], speech_final=False)
        )

        observations = assembler.flush_observations()

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].turn["text"], "final")
        self.assertEqual(observations[0].words[0].start_time_ms, 4000)
        self.assertEqual(assembler.flush_observations(), [])

    def test_new_session_has_fresh_speaker_mapping(self) -> None:
        first_session = SpeakerTurnAssembler()
        second_session = SpeakerTurnAssembler()

        first_turn = first_session.consume(
            result([word("one", 0.0, 0.2, 3)], speech_final=True)
        )[0]
        second_turn = second_session.consume(
            result([word("two", 0.0, 0.2, 8)], speech_final=True)
        )[0]

        self.assertEqual(first_turn["speaker"], "advisor")
        self.assertEqual(second_turn["speaker"], "advisor")

    def test_observation_keeps_word_timing_backend_only(self) -> None:
        assembler = SpeakerTurnAssembler()
        observations = assembler.consume_observations(
            result([word("hello", 1.0, 1.4, 0)], speech_final=True)
        )

        self.assertEqual(observations[0].words[0].start_time_ms, 1000)
        self.assertNotIn("words", observations[0].turn)


class ReflectionTranscriptAssemblerTests(unittest.TestCase):
    def test_collects_only_final_single_speaker_text(self) -> None:
        assembler = ReflectionTranscriptAssembler()

        assembler.consume(result([word("interim", 0.0, 0.2, 0)], is_final=False))
        assembler.consume(result([word("first", 0.0, 0.2, 0, "First.")]))
        assembler.consume(result([word("thought", 0.3, 0.6, 0, "thought.")]))

        self.assertEqual(assembler.text(), "First. thought.")

    def test_empty_dictation_stays_empty(self) -> None:
        self.assertEqual(ReflectionTranscriptAssembler().text(), "")


def coaching_observation(
    turn_id: str,
    *,
    word_count: int = 4,
    start_ms: int = 0,
    end_ms: int = 1_000,
) -> TurnObservation:
    word_duration = max(1, (end_ms - start_ms) // word_count)
    words = tuple(
        TimedWord(
            f"word{index}",
            start_ms + index * word_duration,
            min(end_ms, start_ms + (index + 1) * word_duration),
        )
        for index in range(word_count)
    )
    return TurnObservation(
        {
            "id": turn_id,
            "speaker": "advisor",
            "text": " ".join(word.text for word in words),
            "startTimeMs": start_ms,
            "endTimeMs": end_ms,
            "durationMs": end_ms - start_ms,
            "isFinal": True,
        },
        words,
    )


class FailingSemanticAnalyzer:
    async def analyze(self, snapshot):
        raise TimeoutError


class LateSemanticAnalyzer:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def analyze(self, snapshot):
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            return "late", [
                DetectedEvent(
                    CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
                    EventType.MISSED_EMOTIONAL_CUE,
                    Confidence.HIGH,
                    1_000,
                    "late result",
                )
            ]
        return "", []


class CoachedObservationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_finalized_turn_emits_eligible_behavioral_live_nudge(self) -> None:
        messages = []

        async def send(payload):
            messages.append(payload)
            return True

        session = CoachingSession()
        await emit_coached_observation(
            coaching_observation("a1", word_count=60, end_ms=18_000),
            session,
            send,
        )

        self.assertEqual([message["type"] for message in messages], ["speaker_turn", "live_nudge"])
        self.assertEqual(messages[1]["nudge"]["nudgeKey"], "PACE_SLOW_DOWN")
        await session.close()

    async def test_semantic_failure_does_not_break_finalized_turn_delivery(self) -> None:
        messages = []

        async def send(payload):
            messages.append(payload)
            return True

        session = CoachingSession(FailingSemanticAnalyzer())
        await emit_coached_observation(coaching_observation("a1"), session, send)
        await asyncio.sleep(0.01)

        self.assertEqual([message["type"] for message in messages], ["speaker_turn"])
        await session.close()

    async def test_late_semantic_result_after_close_cannot_emit_into_new_session(self) -> None:
        messages = []

        async def send(payload):
            messages.append(payload)
            return True

        analyzer = LateSemanticAnalyzer()
        old_session = CoachingSession(analyzer)
        await emit_coached_observation(coaching_observation("old"), old_session, send)
        await analyzer.started.wait()
        await old_session.close()

        new_session = CoachingSession()
        await emit_coached_observation(coaching_observation("new"), new_session, send)
        analyzer.release.set()
        await asyncio.sleep(0.01)

        self.assertEqual([message["type"] for message in messages], ["speaker_turn", "speaker_turn"])
        await new_session.close()


class CompletedSnapshotIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_final_flushed_turn_is_registered_in_completed_snapshot(self) -> None:
        assembler = SpeakerTurnAssembler()
        observations = assembler.consume_observations(
            result(
                [word("last", 3.0, 3.3, 0), word("phrase", 3.3, 3.8, 0)],
                from_finalize=True,
            )
        )
        coaching = CoachingSession()
        for observation in observations:
            coaching.observe(observation)
        frozen = await coaching.freeze()
        session = post_meeting_store.register("final-flush-test", frozen)

        self.assertEqual(session.snapshot.turns[0]["text"], "last phrase")
        post_meeting_store.delete("final-flush-test")


if __name__ == "__main__":
    unittest.main()
