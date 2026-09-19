import unittest
from types import SimpleNamespace

from app.coaching import (
    CoachingArea,
    Confidence,
    ContextSnapshot,
    EventType,
    NudgeDecider,
    NudgeKey,
)
from app.semantic_analysis import OpenAISemanticAnalyzer, SemanticAnalysisResult


class FakeResponses:
    def __init__(self, parsed: SemanticAnalysisResult | None) -> None:
        self.parsed = parsed
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=self.parsed)


def turn(turn_id: str, speaker: str, text: str, start_ms: int, end_ms: int):
    return {
        "id": turn_id,
        "speaker": speaker,
        "text": text,
        "startTimeMs": start_ms,
        "endTimeMs": end_ms,
    }


class SemanticAnalysisTests(unittest.TestCase):
    def snapshot(self, turns=None, selected_focus=()) -> ContextSnapshot:
        if turns is None:
            turns = (
                turn("c1", "customer", "I am worried about losing the house.", 0, 2_000),
                turn("a1", "advisor", "Let us look at the options.", 2_500, 4_000),
            )
        return ContextSnapshot(1, tuple(turns), (), (), tuple(selected_focus), "")

    @staticmethod
    def result(events) -> SemanticAnalysisResult:
        return SemanticAnalysisResult.model_validate(
            {"context_summary": "The customer shared a concern.", "events": events}
        )

    def analyze(self, parsed, snapshot=None):
        responses = FakeResponses(parsed)
        analyzer = OpenAISemanticAnalyzer(SimpleNamespace(responses=responses))
        summary, events = analyzer._analyze_sync(snapshot or self.snapshot())
        return summary, events, responses

    def test_structured_result_is_converted_and_timestamped(self) -> None:
        parsed = self.result(
            [
                {
                    "area": CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
                    "type": EventType.MISSED_EMOTIONAL_CUE,
                    "confidence": Confidence.HIGH,
                    "evidence_turn_ids": ["c1", "a1"],
                    "evidence": "The response bypassed the concern.",
                    "nudge_key": NudgeKey.ACKNOWLEDGE_EMOTION,
                }
            ]
        )
        summary, events, responses = self.analyze(parsed)
        self.assertEqual(summary, "The customer shared a concern.")
        self.assertEqual(events[0].timestamp_ms, 4_000)
        self.assertFalse(responses.kwargs["store"])
        self.assertEqual(responses.kwargs["reasoning"], {"effort": "none"})

    def test_customer_cue_uses_customer_evidence_and_has_no_nudge_key(self) -> None:
        parsed = self.result(
            [
                {
                    "area": CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
                    "type": EventType.CUSTOMER_EMOTIONAL_CUE,
                    "confidence": Confidence.HIGH,
                    "evidence_turn_ids": ["c1"],
                    "evidence": "Explicit concern.",
                    "nudge_key": None,
                }
            ]
        )
        _, events, _ = self.analyze(parsed)
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].nudge_key)

    def test_canonical_type_area_and_nudge_combinations_are_required(self) -> None:
        invalid_candidates = (
            {
                "area": CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
                "type": EventType.CLOSED_QUESTION_PATTERN,
                "evidence_turn_ids": ["a1"],
                "nudge_key": NudgeKey.ASK_OPEN_QUESTION,
            },
            {
                "area": CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
                "type": EventType.CUSTOMER_EMOTIONAL_CUE,
                "evidence_turn_ids": ["c1"],
                "nudge_key": NudgeKey.ACKNOWLEDGE_EMOTION,
            },
            {
                "area": CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
                "type": EventType.MISSED_EMOTIONAL_CUE,
                "evidence_turn_ids": ["c1", "a1"],
                "nudge_key": NudgeKey.STAY_BEFORE_SOLVING,
            },
            {
                "area": CoachingArea.OPEN_QUESTIONS,
                "type": EventType.PREMATURE_PROBLEM_SOLVING,
                "evidence_turn_ids": ["c1", "a1"],
                "nudge_key": NudgeKey.STAY_BEFORE_SOLVING,
            },
        )
        for candidate in invalid_candidates:
            with self.subTest(event_type=candidate["type"]):
                parsed = self.result(
                    [
                        {
                            **candidate,
                            "confidence": Confidence.HIGH,
                            "evidence": "Evidence for the candidate.",
                        }
                    ]
                )
                _, events, _ = self.analyze(parsed)
                self.assertEqual(events, [])

    def test_open_question_focus_wins_when_both_events_are_high_confidence(self) -> None:
        snapshot = self.snapshot(
            (
                turn("a1", "advisor", "Tell me what you would like help with.", 0, 2_000),
                turn("c1", "customer", "I am unsure and worried about the decision.", 2_500, 5_000),
                turn(
                    "a2",
                    "advisor",
                    "Is your income fixed? Do you have savings? Do you own a property?",
                    5_500,
                    9_000,
                ),
            ),
            (CoachingArea.OPEN_QUESTIONS,),
        )
        parsed = self.result(
            [
                {
                    "area": CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
                    "type": EventType.MISSED_EMOTIONAL_CUE,
                    "confidence": Confidence.HIGH,
                    "evidence_turn_ids": ["c1", "a2"],
                    "evidence": "The concern was bypassed.",
                    "nudge_key": NudgeKey.ACKNOWLEDGE_EMOTION,
                },
                {
                    "area": CoachingArea.OPEN_QUESTIONS,
                    "type": EventType.CLOSED_QUESTION_PATTERN,
                    "confidence": Confidence.HIGH,
                    "evidence_turn_ids": ["a2"],
                    "evidence": "Several consecutive narrow questions were asked.",
                    "nudge_key": NudgeKey.ASK_OPEN_QUESTION,
                },
            ]
        )

        _, events, _ = self.analyze(parsed, snapshot)
        nudge = NudgeDecider().decide(events, set(snapshot.selected_focus))

        self.assertIsNotNone(nudge)
        self.assertEqual(nudge.nudge_key, NudgeKey.ASK_OPEN_QUESTION)

    def test_all_advisor_transcript_rejects_customer_dependent_events(self) -> None:
        all_advisor = self.snapshot(
            (
                turn("a1", "advisor", "Hello. What would you like help with today?", 0, 2_000),
                turn("a2", "advisor", "Since my partner died handling all of this has felt overwhelming.", 2_500, 5_000),
                turn("a3", "advisor", "We can move the money into these three products.", 5_500, 8_000),
            )
        )
        parsed = self.result(
            [
                {
                    "area": CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
                    "type": EventType.CUSTOMER_EMOTIONAL_CUE,
                    "confidence": Confidence.HIGH,
                    "evidence_turn_ids": ["a2"],
                    "evidence": "An emotional disclosure was made.",
                    "nudge_key": None,
                },
                {
                    "area": CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
                    "type": EventType.MISSED_EMOTIONAL_CUE,
                    "confidence": Confidence.HIGH,
                    "evidence_turn_ids": ["a2", "a3"],
                    "evidence": "The disclosure was bypassed.",
                    "nudge_key": NudgeKey.ACKNOWLEDGE_EMOTION,
                },
                {
                    "area": CoachingArea.STAY_BEFORE_SOLVING,
                    "type": EventType.PREMATURE_PROBLEM_SOLVING,
                    "confidence": Confidence.HIGH,
                    "evidence_turn_ids": ["a2", "a3"],
                    "evidence": "The response moved directly to products.",
                    "nudge_key": NudgeKey.STAY_BEFORE_SOLVING,
                },
            ]
        )
        _, events, _ = self.analyze(parsed, all_advisor)
        self.assertEqual(events, [])

    def test_missing_evidence_id_rejects_entire_candidate(self) -> None:
        parsed = self.result(
            [
                {
                    "area": CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
                    "type": EventType.MISSED_EMOTIONAL_CUE,
                    "confidence": Confidence.HIGH,
                    "evidence_turn_ids": ["c1", "missing", "a1"],
                    "evidence": "The response bypassed the concern.",
                    "nudge_key": NudgeKey.ACKNOWLEDGE_EMOTION,
                }
            ]
        )
        _, events, _ = self.analyze(parsed)
        self.assertEqual(events, [])

    def test_customer_must_precede_advisor_for_response_events(self) -> None:
        reversed_roles = self.snapshot(
            (
                turn("a1", "advisor", "Let us look at the options.", 0, 2_000),
                turn("c1", "customer", "I am worried.", 2_500, 4_000),
            )
        )
        parsed = self.result(
            [
                {
                    "area": CoachingArea.STAY_BEFORE_SOLVING,
                    "type": EventType.PREMATURE_PROBLEM_SOLVING,
                    "confidence": Confidence.HIGH,
                    "evidence_turn_ids": ["c1", "a1"],
                    "evidence": "The response moved directly to products.",
                    "nudge_key": NudgeKey.STAY_BEFORE_SOLVING,
                }
            ]
        )
        _, events, _ = self.analyze(parsed, reversed_roles)
        self.assertEqual(events, [])

    def test_closed_question_requires_advisor_evidence(self) -> None:
        parsed = self.result(
            [
                {
                    "area": CoachingArea.OPEN_QUESTIONS,
                    "type": EventType.CLOSED_QUESTION_PATTERN,
                    "confidence": Confidence.HIGH,
                    "evidence_turn_ids": ["c1"],
                    "evidence": "A narrow question was asked.",
                    "nudge_key": NudgeKey.ASK_OPEN_QUESTION,
                }
            ]
        )
        _, events, _ = self.analyze(parsed)
        self.assertEqual(events, [])

    def test_missing_parsed_output_returns_no_events(self) -> None:
        summary, events, _ = self.analyze(None)
        self.assertEqual(summary, "")
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
