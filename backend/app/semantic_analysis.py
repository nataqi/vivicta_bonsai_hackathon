import asyncio
import json
import os
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from app.coaching import (
    CoachingArea,
    Confidence,
    ContextSnapshot,
    DetectedEvent,
    EventType,
    NudgeKey,
)

MODEL = "gpt-5.6-luna"

INSTRUCTIONS = """You classify live conversation coaching events for a financial adviser.
Coach only the adviser. Return only schema-valid structured output. Never generate coaching prose.
The provided speaker field is authoritative. Never infer or change a speaker role from utterance text.
Use high confidence only for explicit, unambiguous evidence; medium for plausible but ambiguous
evidence; low when substantial inference is required. For CLOSED_QUESTION_PATTERN, high confidence
requires a clear cluster of consecutive narrow or closed adviser questions where open exploration
would have been appropriate; one necessary factual or compliance question is not automatically a
coaching issue. Detect events independently of selectedFocus, which affects downstream priority
only. Return every independently supported event; do not omit one because another is also present.
CUSTOMER_EMOTIONAL_CUE is context only and must have no nudge key.
After a customer cue, inspect the adviser's next response. If it acknowledges or explores the cue,
emit no actionable event. Only if it clearly bypasses or ignores the cue may you emit
MISSED_EMOTIONAL_CUE with ACKNOWLEDGE_EMOTION. Emit PREMATURE_PROBLEM_SOLVING only when the adviser
moves directly into advice, numbers, or solutions before acknowledging or exploring a significant
disclosure. Allowed event types and nudge keys are enforced by the schema. Return no event when
evidence is insufficient. Evidence must be a brief reason without copying customer quotations."""


class SemanticCandidate(BaseModel):
    area: CoachingArea
    type: Literal[
        EventType.CLOSED_QUESTION_PATTERN,
        EventType.CUSTOMER_EMOTIONAL_CUE,
        EventType.MISSED_EMOTIONAL_CUE,
        EventType.PREMATURE_PROBLEM_SOLVING,
    ]
    confidence: Confidence
    evidence_turn_ids: list[str] = Field(max_length=4)
    evidence: str = Field(max_length=180)
    nudge_key: NudgeKey | None = None


class SemanticAnalysisResult(BaseModel):
    context_summary: str = Field(max_length=300)
    events: list[SemanticCandidate] = Field(max_length=4)


CANONICAL_EVENT_FIELDS: dict[EventType, tuple[CoachingArea, NudgeKey | None]] = {
    EventType.CLOSED_QUESTION_PATTERN: (
        CoachingArea.OPEN_QUESTIONS,
        NudgeKey.ASK_OPEN_QUESTION,
    ),
    EventType.CUSTOMER_EMOTIONAL_CUE: (
        CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
        None,
    ),
    EventType.MISSED_EMOTIONAL_CUE: (
        CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
        NudgeKey.ACKNOWLEDGE_EMOTION,
    ),
    EventType.PREMATURE_PROBLEM_SOLVING: (
        CoachingArea.STAY_BEFORE_SOLVING,
        NudgeKey.STAY_BEFORE_SOLVING,
    ),
}


class OpenAISemanticAnalyzer:
    def __init__(self, client: OpenAI, timeout_seconds: float = 4.0) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> "OpenAISemanticAnalyzer | None":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        return cls(OpenAI(api_key=api_key, timeout=4.0, max_retries=0))

    async def analyze(self, snapshot: ContextSnapshot) -> tuple[str, list[DetectedEvent]]:
        return await asyncio.wait_for(
            asyncio.to_thread(self._analyze_sync, snapshot),
            timeout=self.timeout_seconds + 0.5,
        )

    def _analyze_sync(self, snapshot: ContextSnapshot) -> tuple[str, list[DetectedEvent]]:
        response = self.client.responses.parse(
            model=MODEL,
            reasoning={"effort": "none"},
            instructions=INSTRUCTIONS,
            input=json.dumps(self._payload(snapshot), separators=(",", ":")),
            text_format=SemanticAnalysisResult,
            max_output_tokens=500,
            store=False,
        )
        parsed = response.output_parsed
        if parsed is None:
            return snapshot.summary, []
        turns_by_id = {str(turn["id"]): turn for turn in snapshot.turns}
        events: list[DetectedEvent] = []
        for candidate in parsed.events:
            if (
                candidate.area,
                candidate.nudge_key,
            ) != CANONICAL_EVENT_FIELDS[candidate.type]:
                continue
            if not candidate.evidence_turn_ids or any(
                turn_id not in turns_by_id for turn_id in candidate.evidence_turn_ids
            ):
                continue
            evidence_turns = [turns_by_id[turn_id] for turn_id in candidate.evidence_turn_ids]
            if not self._has_valid_role_evidence(candidate.type, evidence_turns):
                continue
            events.append(
                DetectedEvent(
                    candidate.area,
                    EventType(candidate.type),
                    candidate.confidence,
                    max(int(turn["endTimeMs"]) for turn in evidence_turns),
                    candidate.evidence,
                    tuple(candidate.evidence_turn_ids),
                    candidate.nudge_key,
                )
            )
        return parsed.context_summary, events

    @staticmethod
    def _has_valid_role_evidence(
        event_type: EventType,
        evidence_turns: list[dict[str, object]],
    ) -> bool:
        if event_type == EventType.CUSTOMER_EMOTIONAL_CUE:
            return any(turn["speaker"] == "customer" for turn in evidence_turns)
        if event_type == EventType.CLOSED_QUESTION_PATTERN:
            return any(turn["speaker"] == "advisor" for turn in evidence_turns)
        if event_type in {
            EventType.MISSED_EMOTIONAL_CUE,
            EventType.PREMATURE_PROBLEM_SOLVING,
        }:
            customer_starts = [
                int(turn["startTimeMs"])
                for turn in evidence_turns
                if turn["speaker"] == "customer"
            ]
            advisor_starts = [
                int(turn["startTimeMs"])
                for turn in evidence_turns
                if turn["speaker"] == "advisor"
            ]
            return any(
                customer_start < advisor_start
                for customer_start in customer_starts
                for advisor_start in advisor_starts
            )
        return False

    @staticmethod
    def _payload(snapshot: ContextSnapshot) -> dict[str, object]:
        return {
            "selectedFocus": [area.value for area in snapshot.selected_focus],
            "currentContext": snapshot.summary,
            "recentTurns": [
                {
                    "id": turn["id"],
                    "speaker": turn["speaker"],
                    "text": turn["text"],
                    "startTimeMs": turn["startTimeMs"],
                    "endTimeMs": turn["endTimeMs"],
                }
                for turn in snapshot.turns
            ],
            "recentEvents": [
                {"area": event.area.value, "type": event.type.value, "confidence": event.confidence.value}
                for event in snapshot.events
            ],
            "recentNudges": [nudge.nudge_key.value for nudge in snapshot.nudges],
        }
