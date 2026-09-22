import asyncio
import json
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
from app.openrouter import (
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    OPENROUTER_STRUCTURED_PROVIDER,
    openrouter_api_key,
    structured_response_format,
)

MODEL = OPENROUTER_MODEL

# Kept as tight as the rules allow: this is re-sent and re-processed on every live call, and
# every sentence here maps to a rule tests rely on (role authority, per-type confidence rubric,
# the emotional-cue/premature-solving pair, schema enforcement, no quotations). Trim wording,
# not rules.
INSTRUCTIONS = """Classify live coaching events for a financial adviser. Coach only the adviser:
return schema-valid structured output only, never prose. The speaker field is authoritative; never
infer or change it from utterance text. Confidence: high only for explicit, unambiguous evidence;
medium for plausible but ambiguous evidence; low when substantial inference is required.
CLOSED_QUESTION_PATTERN needs high confidence only for a clear cluster of consecutive narrow/closed
adviser questions where open exploration was appropriate; one necessary factual or compliance
question is not a coaching issue. Detect events independently of selectedFocus (it only affects
downstream priority); return every independently supported event, even alongside others.
CUSTOMER_EMOTIONAL_CUE is context only, with no nudge key. After a customer cue, check the adviser's
next response: if it acknowledges or explores the cue, emit nothing; only if it clearly bypasses the
cue, emit MISSED_EMOTIONAL_CUE with ACKNOWLEDGE_EMOTION. Emit PREMATURE_PROBLEM_SOLVING only when the
adviser moves directly into advice, numbers, or solutions before acknowledging or exploring a
significant disclosure. Event types and nudge keys are schema-enforced. Return no event when
evidence is insufficient. Evidence must be a brief reason, never a customer quotation."""


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


class OpenRouterSemanticAnalyzer:
    def __init__(self, client: OpenAI, timeout_seconds: float = 4.0) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> "OpenRouterSemanticAnalyzer | None":
        api_key = openrouter_api_key()
        if not api_key:
            return None
        return cls(
            OpenAI(
                api_key=api_key,
                base_url=OPENROUTER_BASE_URL,
                timeout=4.0,
                max_retries=0,
            )
        )

    async def analyze(self, snapshot: ContextSnapshot) -> tuple[str, list[DetectedEvent]]:
        return await asyncio.wait_for(
            asyncio.to_thread(self._analyze_sync, snapshot),
            timeout=self.timeout_seconds + 0.5,
        )

    def _analyze_sync(self, snapshot: ContextSnapshot) -> tuple[str, list[DetectedEvent]]:
        response = self.client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": INSTRUCTIONS},
                {
                    "role": "user",
                    "content": json.dumps(self._payload(snapshot), separators=(",", ":")),
                },
            ],
            response_format=structured_response_format(SemanticAnalysisResult),
            # Right-sized for the schema's realistic shape (300-char summary + up to 4 events),
            # not the pathological worst case of 4 maxed-out events, which the model's own
            # "return every independently supported event" instruction makes rare in practice.
            max_tokens=400,
            extra_body=OPENROUTER_STRUCTURED_PROVIDER,
        )
        content = response.choices[0].message.content
        if not content:
            return snapshot.summary, []
        parsed = SemanticAnalysisResult.model_validate_json(content)
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
            if not self._has_valid_role_evidence(
                candidate.type,
                evidence_turns,
                snapshot.turns,
            ):
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
        snapshot_turns: tuple[dict[str, object], ...],
    ) -> bool:
        if event_type == EventType.CUSTOMER_EMOTIONAL_CUE:
            return any(turn["speaker"] == "customer" for turn in evidence_turns)
        if event_type == EventType.CLOSED_QUESTION_PATTERN:
            return any(turn["speaker"] == "advisor" for turn in evidence_turns)
        if event_type in {
            EventType.MISSED_EMOTIONAL_CUE,
            EventType.PREMATURE_PROBLEM_SOLVING,
        }:
            advisor_turns = [turn for turn in evidence_turns if turn["speaker"] == "advisor"]
            customer_ids = {
                str(turn["id"])
                for turn in evidence_turns
                if turn["speaker"] == "customer"
            }
            if len(advisor_turns) != 1 or not customer_ids:
                return False

            advisor_id = str(advisor_turns[0]["id"])
            advisor_index = next(
                (
                    index
                    for index, turn in enumerate(snapshot_turns)
                    if str(turn["id"]) == advisor_id
                ),
                None,
            )
            if advisor_index is None:
                return False

            contribution_ids: set[str] = set()
            index = advisor_index - 1
            while index >= 0 and snapshot_turns[index]["speaker"] == "customer":
                contribution_ids.add(str(snapshot_turns[index]["id"]))
                index -= 1
            return customer_ids.issubset(contribution_ids)
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
                {
                    "area": event.area.value,
                    "type": event.type.value,
                    "confidence": event.confidence.value,
                    "timestampMs": event.timestamp_ms,
                }
                for event in snapshot.events
            ],
            "recentNudges": [nudge.nudge_key.value for nudge in snapshot.nudges],
        }
