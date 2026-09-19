import asyncio
import unittest

from app.coaching import (
    BehavioralAnalyzer,
    CoachingArea,
    CoachingSession,
    Confidence,
    ContextSnapshot,
    DetectedEvent,
    EventType,
    NudgeDecider,
    NudgeKey,
    RollingContext,
    TimedWord,
    TurnObservation,
)


def observation(
    speaker: str,
    start_ms: int,
    end_ms: int,
    *,
    turn_id: str,
    word_count: int = 4,
    text: str | None = None,
) -> TurnObservation:
    duration = max(1, end_ms - start_ms)
    word_duration = max(1, duration // word_count)
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
            "speaker": speaker,
            "text": text or " ".join(word.text for word in words),
            "startTimeMs": start_ms,
            "endTimeMs": end_ms,
            "durationMs": duration,
            "isFinal": True,
        },
        words,
    )


def event(
    event_type: EventType,
    timestamp_ms: int,
    *,
    confidence: Confidence = Confidence.HIGH,
    area: CoachingArea = CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
    nudge_key: NudgeKey | None = None,
) -> DetectedEvent:
    return DetectedEvent(area, event_type, confidence, timestamp_ms, "evidence", nudge_key=nudge_key)


class BehavioralAnalyzerTests(unittest.TestCase):
    def test_sustained_fast_adviser_turn_is_high_confidence(self) -> None:
        analyzer = BehavioralAnalyzer()
        events = analyzer.analyze(
            observation("advisor", 0, 18_000, turn_id="a1", word_count=60)
        )
        pace = next(item for item in events if item.type == EventType.FAST_PACE)
        self.assertEqual(pace.confidence, Confidence.HIGH)

    def test_short_customer_response_gap_is_supporting_evidence_only(self) -> None:
        analyzer = BehavioralAnalyzer()
        analyzer.analyze(observation("customer", 0, 2_000, turn_id="c1"))
        events = analyzer.analyze(observation("advisor", 2_300, 3_000, turn_id="a1"))
        gap = next(item for item in events if item.type == EventType.SHORT_RESPONSE_GAP)
        self.assertEqual(gap.confidence, Confidence.MEDIUM)
        self.assertIsNone(NudgeDecider().decide(events, set()))

    def test_repeated_clear_interruptions_become_high_confidence(self) -> None:
        analyzer = BehavioralAnalyzer()
        analyzer.analyze(observation("customer", 0, 2_000, turn_id="c1"))
        first = analyzer.analyze(observation("advisor", 1_500, 2_500, turn_id="a1"))
        analyzer.analyze(observation("customer", 3_000, 5_000, turn_id="c2"))
        second = analyzer.analyze(observation("advisor", 4_500, 5_500, turn_id="a2"))
        self.assertEqual(
            next(item for item in first if item.type == EventType.INTERRUPTION_PATTERN).confidence,
            Confidence.MEDIUM,
        )
        self.assertEqual(
            next(item for item in second if item.type == EventType.INTERRUPTION_PATTERN).confidence,
            Confidence.HIGH,
        )

    def test_long_monologue_thresholds(self) -> None:
        analyzer = BehavioralAnalyzer()
        medium = analyzer.analyze(observation("advisor", 0, 30_000, turn_id="a1"))
        high = analyzer.analyze(observation("advisor", 40_000, 85_000, turn_id="a2"))
        self.assertEqual(next(e for e in medium if e.type == EventType.LONG_MONOLOGUE).confidence, Confidence.MEDIUM)
        self.assertEqual(next(e for e in high if e.type == EventType.LONG_MONOLOGUE).confidence, Confidence.HIGH)

    def test_talk_time_imbalance_is_supporting_evidence(self) -> None:
        analyzer = BehavioralAnalyzer()
        analyzer.analyze(observation("advisor", 0, 50_000, turn_id="a1", word_count=100))
        events = analyzer.analyze(observation("customer", 60_000, 65_000, turn_id="c1", word_count=10))
        balance = next(item for item in events if item.type == EventType.TALK_TIME_IMBALANCE)
        self.assertEqual(balance.confidence, Confidence.MEDIUM)
        self.assertIsNone(NudgeDecider().decide(events, set()))


class NudgeDecisionTests(unittest.TestCase):
    def test_customer_emotional_cue_never_nudges(self) -> None:
        cue = event(
            EventType.CUSTOMER_EMOTIONAL_CUE,
            10_000,
            nudge_key=NudgeKey.ACKNOWLEDGE_EMOTION,
        )
        self.assertIsNone(NudgeDecider().decide([cue], {cue.area}))

    def test_missed_emotional_cue_maps_to_acknowledgement(self) -> None:
        nudge = NudgeDecider().decide(
            [event(EventType.MISSED_EMOTIONAL_CUE, 10_000)], set()
        )
        self.assertEqual(nudge.nudge_key, NudgeKey.ACKNOWLEDGE_EMOTION)

    def test_medium_semantic_event_does_not_nudge(self) -> None:
        candidate = event(
            EventType.MISSED_EMOTIONAL_CUE,
            10_000,
            confidence=Confidence.MEDIUM,
        )
        self.assertIsNone(NudgeDecider().decide([candidate], set()))

    def test_focus_priority_cooldown_and_repetition(self) -> None:
        decider = NudgeDecider()
        closed = event(
            EventType.CLOSED_QUESTION_PATTERN,
            100_000,
            area=CoachingArea.OPEN_QUESTIONS,
        )
        missed = event(EventType.MISSED_EMOTIONAL_CUE, 99_000)
        first = decider.decide([closed, missed], {CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES})
        self.assertEqual(first.nudge_key, NudgeKey.ACKNOWLEDGE_EMOTION)
        self.assertIsNone(decider.decide([closed], set()))
        different = event(
            EventType.CLOSED_QUESTION_PATTERN,
            180_000,
            area=CoachingArea.OPEN_QUESTIONS,
        )
        self.assertEqual(decider.decide([different], set()).nudge_key, NudgeKey.ASK_OPEN_QUESTION)
        repeated = event(EventType.MISSED_EMOTIONAL_CUE, 190_000)
        self.assertIsNone(decider.decide([repeated], set()))

    def test_invalid_event_key_pair_is_rejected(self) -> None:
        invalid = event(
            EventType.MISSED_EMOTIONAL_CUE,
            10_000,
            nudge_key=NudgeKey.ASK_OPEN_QUESTION,
        )
        self.assertIsNone(NudgeDecider().decide([invalid], set()))


class RollingContextTests(unittest.TestCase):
    def test_turns_are_bounded_by_count_and_characters(self) -> None:
        context = RollingContext()
        for index in range(12):
            context.add_turn(observation("advisor", index, index + 1, turn_id=str(index), text="x" * 180).turn)
        self.assertLessEqual(len(context.turns), 8)
        self.assertLessEqual(sum(len(str(turn["text"])) for turn in context.turns), 1_200)


class FakeAnalyzer:
    def __init__(self, results: list[tuple[str, list[DetectedEvent]]]) -> None:
        self.results = results
        self.calls: list[ContextSnapshot] = []

    async def analyze(self, snapshot: ContextSnapshot) -> tuple[str, list[DetectedEvent]]:
        self.calls.append(snapshot)
        await asyncio.sleep(0)
        return self.results.pop(0)


class BlockingAnalyzer:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.versions: list[int] = []

    async def analyze(self, snapshot: ContextSnapshot) -> tuple[str, list[DetectedEvent]]:
        self.versions.append(snapshot.version)
        if len(self.versions) == 1:
            await self.release.wait()
        return "", []


class FailingAnalyzer:
    async def analyze(self, snapshot: ContextSnapshot) -> tuple[str, list[DetectedEvent]]:
        raise TimeoutError


class CoachingSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_acknowledged_cue_produces_no_nudge(self) -> None:
        analyzer = FakeAnalyzer([("cue retained", [event(EventType.CUSTOMER_EMOTIONAL_CUE, 2_000)]), ("acknowledged", [])])
        session = CoachingSession(analyzer)
        nudges = []
        session.observe(observation("customer", 0, 2_000, turn_id="c1"))
        session.schedule_semantic(lambda nudge: self._capture(nudges, nudge))
        await asyncio.sleep(0.01)
        session.observe(observation("advisor", 2_800, 4_000, turn_id="a1"))
        session.schedule_semantic(lambda nudge: self._capture(nudges, nudge))
        await asyncio.sleep(0.01)
        self.assertEqual(nudges, [])
        await session.close()

    async def test_missed_cue_produces_acknowledgement_nudge(self) -> None:
        missed = event(EventType.MISSED_EMOTIONAL_CUE, 4_000)
        analyzer = FakeAnalyzer([("missed", [missed])])
        session = CoachingSession(analyzer)
        nudges = []
        session.observe(observation("advisor", 2_800, 4_000, turn_id="a1"))
        session.schedule_semantic(lambda nudge: self._capture(nudges, nudge))
        await asyncio.sleep(0.01)
        self.assertEqual(nudges[0].nudge_key, NudgeKey.ACKNOWLEDGE_EMOTION)
        await session.close()

    async def test_semantic_failure_does_not_escape_or_close_session(self) -> None:
        session = CoachingSession(FailingAnalyzer())
        session.observe(observation("customer", 0, 2_000, turn_id="c1"))
        session.schedule_semantic(lambda nudge: self._capture([], nudge))
        await asyncio.sleep(0.01)
        session.observe(observation("advisor", 3_000, 4_000, turn_id="a1"))
        self.assertEqual(session.context.version, 2)
        await session.close()

    async def test_in_flight_analysis_keeps_only_latest_pending_snapshot(self) -> None:
        analyzer = BlockingAnalyzer()
        session = CoachingSession(analyzer)
        callback = lambda nudge: self._capture([], nudge)
        session.observe(observation("customer", 0, 1_000, turn_id="c1"))
        session.schedule_semantic(callback)
        await asyncio.sleep(0)
        session.observe(observation("advisor", 2_000, 3_000, turn_id="a1"))
        session.schedule_semantic(callback)
        session.observe(observation("customer", 4_000, 5_000, turn_id="c2"))
        session.schedule_semantic(callback)
        analyzer.release.set()
        await asyncio.sleep(0.01)
        self.assertEqual(analyzer.versions, [1, 3])
        await session.close()

    @staticmethod
    async def _capture(target: list, nudge: object) -> None:
        target.append(nudge)


if __name__ == "__main__":
    unittest.main()
