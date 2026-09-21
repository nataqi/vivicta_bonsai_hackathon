from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.coaching import (
    CoachingArea,
    CompletedMeetingData,
    DetectedEvent,
    EventType,
    LiveNudge,
)
from app.openrouter import (
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    OPENROUTER_STRUCTURED_PROVIDER,
    openrouter_api_key,
    structured_response_format,
)

logger = logging.getLogger(__name__)
router = APIRouter()

REPORT_MODEL = OPENROUTER_MODEL
REPORT_TIMEOUT_SECONDS = 15.0
REFLECTION_TIMEOUT_SECONDS = 10.0
SESSION_TTL_SECONDS = 30 * 60

BOUNDED_TEXT_LIMITS = {
    "focus_summary": 220,
    "takeaway": 160,
    "reflection_context": 600,
    "coach_message": 300,
}
KEY_MOMENT_TEXT_LIMITS = {
    "customer_context": 160,
    "better_answer": 260,
    "why": 160,
}
BOUNDED_LIST_ITEM_LIMITS = {
    "strengths": 180,
    "improvements": 180,
}

SEMANTIC_EVENT_TYPES = {
    EventType.CLOSED_QUESTION_PATTERN,
    EventType.CUSTOMER_EMOTIONAL_CUE,
    EventType.MISSED_EMOTIONAL_CUE,
    EventType.PREMATURE_PROBLEM_SOLVING,
}

INCOMPLETE_TRAILING_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def bounded_text(value: str, limit: int) -> str:
    """Bound generated prose at a complete sentence or safe word boundary."""
    if len(value) <= limit:
        return value
    prefix = value[:limit]
    sentence_ends = list(re.finditer(r"[.!?](?=\s|$)", prefix))
    if sentence_ends:
        return prefix[: sentence_ends[-1].end()].rstrip()
    if not value[limit].isspace():
        boundary = max(
            (index for index, character in enumerate(prefix) if character.isspace()),
            default=-1,
        )
        prefix = prefix[:boundary] if boundary >= 0 else ""
    bounded = prefix.rstrip()
    while bounded and bounded.rsplit(maxsplit=1)[-1].lower().rstrip(",;:") in INCOMPLETE_TRAILING_WORDS:
        bounded = bounded.rsplit(maxsplit=1)[0] if " " in bounded else ""
    return bounded


class PostMeetingReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strengths: list[str] = Field(min_length=1, max_length=2)
    improvements: list[str] = Field(min_length=1, max_length=2)
    focus_summary: str = Field(min_length=1, max_length=220)
    takeaway: str = Field(min_length=1, max_length=160)

    @field_validator("strengths", "improvements")
    @classmethod
    def validate_items(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item or len(item) > 180 for item in cleaned):
            raise ValueError("Report items must be concise and non-empty")
        return cleaned

    @field_validator("focus_summary", "takeaway")
    @classmethod
    def validate_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Report text must be non-empty")
        return cleaned


class KeyMoment(BaseModel):
    """One adviser turn worth replaying, with a generic paraphrase of the context."""

    model_config = ConfigDict(extra="forbid")

    turn_id: str = Field(min_length=1, max_length=64)
    area: CoachingArea
    kind: Literal["improvement", "strength"]
    customer_context: str = Field(min_length=1, max_length=160)
    better_answer: str = Field(min_length=1, max_length=260)
    why: str = Field(min_length=1, max_length=160)

    @field_validator("turn_id", "customer_context", "better_answer", "why")
    @classmethod
    def clean_key_moment_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Key moment text must be non-empty")
        return cleaned


class KeyMomentView(KeyMoment):
    start_time_ms: int
    end_time_ms: int


class InternalReport(PostMeetingReport):
    reflection_context: str = Field(min_length=1, max_length=600)
    strength_areas: list[CoachingArea] = Field(min_length=0, max_length=2)
    improvement_areas: list[CoachingArea] = Field(min_length=0, max_length=2)
    key_moment: KeyMoment | None = Field(...)

    @field_validator("reflection_context")
    @classmethod
    def validate_reflection_context(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Reflection context must be non-empty")
        return cleaned

    @field_validator("strength_areas", "improvement_areas")
    @classmethod
    def unique_learning_areas(cls, value: list[CoachingArea]) -> list[CoachingArea]:
        if len(set(value)) != len(value):
            raise ValueError("Learning areas must be unique")
        return value


class ReflectionFollowUp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coach_message: str = Field(min_length=1, max_length=300)

    @field_validator("coach_message")
    @classmethod
    def clean_coach_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Coach message must be non-empty")
        return cleaned


class ReflectionCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coach_message: str = Field(min_length=1, max_length=300)
    takeaway: str = Field(min_length=1, max_length=160)
    takeaway_area: CoachingArea | None = Field(...)

    @field_validator("coach_message", "takeaway")
    @classmethod
    def clean_completion_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Reflection text must be non-empty")
        return cleaned


class ReflectionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: UUID = Field(alias="messageId")
    message: str = Field(min_length=1, max_length=800)

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Reflection message must be non-empty")
        return cleaned


class ReflectionResponse(BaseModel):
    coach_message: str
    complete: bool
    takeaway: str | None = None


class ReportResponse(BaseModel):
    report: PostMeetingReport
    key_moment: KeyMomentView | None = None


@dataclass(frozen=True)
class CompletedMeetingSnapshot:
    session_id: str
    created_at: float
    turns: tuple[dict[str, object], ...]
    selected_focus: tuple[CoachingArea, ...]
    behavioral_events: tuple[DetectedEvent, ...]
    semantic_events: tuple[DetectedEvent, ...]
    nudges: tuple[LiveNudge, ...]


@dataclass
class PostMeetingSession:
    snapshot: CompletedMeetingSnapshot
    report: PostMeetingReport | None = None
    reflection_context: str | None = None
    strength_areas: tuple[CoachingArea, ...] = ()
    improvement_areas: tuple[CoachingArea, ...] = ()
    takeaway_area: CoachingArea | None = None
    reflection_messages: list[dict[str, str]] = field(default_factory=list)
    processed_reflection_requests: dict[str, ReflectionResponse] = field(default_factory=dict)
    reflection_reply_count: int = 0
    key_moment: KeyMoment | None = None
    voice_id: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    voice_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    expires_at: float = 0.0


class PostMeetingStore:
    def __init__(self, ttl_seconds: float = SESSION_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, PostMeetingSession] = {}
        # Set by app.voice so a provider-side cloned voice is removed with its session.
        self.voice_discard_hook: Callable[[str], None] | None = None

    def _discard(self, session: PostMeetingSession | None) -> None:
        if session is not None and session.voice_id and self.voice_discard_hook is not None:
            self.voice_discard_hook(session.voice_id)

    def _purge_expired(self) -> None:
        now = time.monotonic()
        for session_id, session in tuple(self._sessions.items()):
            if session.expires_at <= now:
                self._discard(self._sessions.pop(session_id, None))

    def register(self, session_id: str, data: CompletedMeetingData) -> PostMeetingSession:
        self._purge_expired()
        event_split = lambda event: event.type in SEMANTIC_EVENT_TYPES
        snapshot = CompletedMeetingSnapshot(
            session_id=session_id,
            created_at=time.time(),
            turns=tuple(dict(turn) for turn in data.turns),
            selected_focus=tuple(data.selected_focus),
            behavioral_events=tuple(event for event in data.events if not event_split(event)),
            semantic_events=tuple(event for event in data.events if event_split(event)),
            nudges=tuple(data.nudges),
        )
        session = PostMeetingSession(snapshot=snapshot)
        session.expires_at = time.monotonic() + self.ttl_seconds
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> PostMeetingSession | None:
        self._purge_expired()
        session = self._sessions.get(session_id)
        if session is not None:
            session.expires_at = time.monotonic() + self.ttl_seconds
        return session

    def delete(self, session_id: str) -> None:
        self._purge_expired()
        self._discard(self._sessions.pop(session_id, None))

    def clear(self) -> None:
        for session in self._sessions.values():
            self._discard(session)
        self._sessions.clear()


store = PostMeetingStore()


class PostMeetingAIError(Exception):
    pass


class PostMeetingAI:
    def __init__(
        self,
        client: Any | None = None,
        report_timeout: float = REPORT_TIMEOUT_SECONDS,
        reflection_timeout: float = REFLECTION_TIMEOUT_SECONDS,
    ) -> None:
        self.client = client
        self.report_timeout = report_timeout
        self.reflection_timeout = reflection_timeout

    @classmethod
    def from_environment(cls) -> "PostMeetingAI":
        api_key = openrouter_api_key()
        if not api_key:
            return cls()
        return cls(
            AsyncOpenAI(
                api_key=api_key,
                base_url=OPENROUTER_BASE_URL,
                timeout=12.0,
                max_retries=0,
            )
        )

    def _require_client(self) -> Any:
        if self.client is None:
            raise PostMeetingAIError("OpenRouter is not configured")
        return self.client

    async def generate_report(self, snapshot: CompletedMeetingSnapshot) -> InternalReport:
        payload = build_report_payload(snapshot)
        instructions = """You are a private coaching assistant for a financial adviser.
Review the complete finalized meeting context and return only the requested structured report.
Coach the adviser, not the customer. Evaluate all five dimensions: pace and pauses, turn-taking
and interruptions, open questions, acknowledging emotional cues, and staying with the customer
before solving. Prioritize selected focus areas, but do not ignore clear evidence elsewhere.
Use qualitative, supportive, specific language. Do not provide scores, rankings, financial advice,
customer summaries, customer quotations, names, or customer-specific details. Never copy a quote.
Choose at most two concise strengths and two actionable improvements. Also classify each selected
strength and improvement using distinct canonical coaching areas with no duplicates, using only the
five canonical coaching area identifiers in the schema.
The reflection_context must be a short generic summary of adviser behavior, with no customer details or quotes.
Also choose one key_moment for the adviser to replay: a single adviser turn, referenced by the exact id
of one finalized turn whose speaker is "advisor". Prefer the most coachable improvement moment,
prioritizing selected focus areas, and set kind to "improvement". Only if there is no improvement
moment, choose the adviser's best moment and set kind to "strength". Use null for key_moment if no
adviser turn is suitable. For the key_moment, customer_context is a generic paraphrase of what the
customer conveyed (no quotes, names, numbers, or identifying details), better_answer is what the
adviser could say instead (or an even stronger version of a strength) in first person, one or two short
sentences of roughly the same length as the original turn, warm and natural, with no financial advice
or figures, and why is one short line explaining what makes the better answer work."""
        parsed = await self._parse(
            InternalReport,
            instructions,
            payload,
            max_output_tokens=800,
            timeout=self.report_timeout,
        )
        try:
            report = InternalReport.model_validate(parsed)
        except Exception as error:
            raise PostMeetingAIError("Invalid report output") from error
        if report.key_moment is not None and find_advisor_turn(snapshot, report.key_moment.turn_id) is None:
            report = report.model_copy(update={"key_moment": None})
        return report

    async def generate_reflection_follow_up(
        self,
        snapshot: CompletedMeetingSnapshot,
        report: PostMeetingReport,
        reflection_context: str,
        messages: list[dict[str, str]],
    ) -> ReflectionFollowUp:
        instructions = reflection_instructions(
            "follow_up",
            snapshot,
            report,
            reflection_context,
            messages,
        )
        parsed = await self._parse(
            ReflectionFollowUp,
            instructions,
            {"reply": messages[-1]["content"], "history": messages},
            max_output_tokens=300,
            timeout=self.reflection_timeout,
        )
        try:
            return ReflectionFollowUp.model_validate(parsed)
        except Exception as error:
            raise PostMeetingAIError("Invalid reflection output") from error

    async def generate_reflection_completion(
        self,
        snapshot: CompletedMeetingSnapshot,
        report: PostMeetingReport,
        reflection_context: str,
        messages: list[dict[str, str]],
    ) -> ReflectionCompletion:
        instructions = reflection_instructions(
            "completion",
            snapshot,
            report,
            reflection_context,
            messages,
        )
        parsed = await self._parse(
            ReflectionCompletion,
            instructions,
            {"reply": messages[-1]["content"], "history": messages},
            max_output_tokens=350,
            timeout=self.reflection_timeout,
        )
        try:
            return ReflectionCompletion.model_validate(parsed)
        except Exception as error:
            raise PostMeetingAIError("Invalid reflection output") from error

    async def _parse(
        self,
        schema: type[BaseModel],
        instructions: str,
        payload: dict[str, object],
        *,
        max_output_tokens: int,
        timeout: float,
    ) -> BaseModel:
        client = self._require_client()
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=REPORT_MODEL,
                    messages=[
                        {"role": "system", "content": instructions},
                        {
                            "role": "user",
                            "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        },
                    ],
                    response_format=structured_response_format(schema),
                    max_tokens=max_output_tokens,
                    extra_body=OPENROUTER_STRUCTURED_PROVIDER,
                ),
                timeout=timeout,
            )
        except Exception as error:
            raise PostMeetingAIError("OpenRouter request failed") from error
        content = response.choices[0].message.content
        if not content:
            raise PostMeetingAIError("OpenRouter returned no structured output")
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError as error:
            details = [{"type": "json_invalid", "loc": ()}]
            logger.warning(
                "OpenRouter structured output validation failed: count=%d errors=%s",
                len(details),
                details,
            )
            raise PostMeetingAIError("Invalid structured output") from error
        if not isinstance(decoded, dict):
            raise PostMeetingAIError("Invalid structured output")
        normalized = dict(decoded)
        for field_name in ("strength_areas", "improvement_areas"):
            value = normalized.get(field_name)
            if isinstance(value, list):
                deduplicated: list[object] = []
                for item in value:
                    if not any(item == existing for existing in deduplicated):
                        deduplicated.append(item)
                normalized[field_name] = deduplicated
        for field_name, limit in BOUNDED_TEXT_LIMITS.items():
            value = normalized.get(field_name)
            if isinstance(value, str):
                normalized[field_name] = bounded_text(value, limit)
        for field_name, limit in BOUNDED_LIST_ITEM_LIMITS.items():
            value = normalized.get(field_name)
            if isinstance(value, list):
                normalized[field_name] = [
                    bounded_text(item, limit) if isinstance(item, str) else item for item in value
                ]
        key_moment = normalized.get("key_moment")
        if isinstance(key_moment, dict):
            normalized["key_moment"] = {
                name: bounded_text(value, KEY_MOMENT_TEXT_LIMITS[name])
                if name in KEY_MOMENT_TEXT_LIMITS and isinstance(value, str)
                else value
                for name, value in key_moment.items()
            }
        try:
            return schema.model_validate(normalized)
        except ValidationError as error:
            details = [
                {"type": item["type"], "loc": item["loc"]}
                for item in error.errors(include_input=False)
            ]
            logger.warning(
                "OpenRouter structured output validation failed: count=%d errors=%s",
                len(details),
                details,
            )
            raise PostMeetingAIError("Invalid structured output") from error
        except Exception as error:
            raise PostMeetingAIError("Invalid structured output") from error


_ai_service: PostMeetingAI | None = None


def get_ai_service() -> PostMeetingAI:
    global _ai_service
    if _ai_service is None:
        _ai_service = PostMeetingAI.from_environment()
    return _ai_service


def build_report_payload(snapshot: CompletedMeetingSnapshot) -> dict[str, object]:
    return {
        "selectedFocus": [area.value for area in snapshot.selected_focus],
        "finalizedTurns": list(snapshot.turns),
        "behavioralEvents": [event_payload(event) for event in snapshot.behavioral_events],
        "semanticEvents": [event_payload(event) for event in snapshot.semantic_events],
        "displayedNudges": [nudge_payload(nudge) for nudge in snapshot.nudges],
    }


def find_advisor_turn(snapshot: CompletedMeetingSnapshot, turn_id: str) -> dict[str, object] | None:
    for turn in snapshot.turns:
        if turn.get("id") == turn_id and turn.get("speaker") == "advisor":
            return turn
    return None


def key_moment_view(session: PostMeetingSession) -> KeyMomentView | None:
    moment = session.key_moment
    if moment is None:
        return None
    turn = find_advisor_turn(session.snapshot, moment.turn_id)
    if turn is None:
        return None
    return KeyMomentView(
        **moment.model_dump(),
        start_time_ms=int(turn["startTimeMs"]),
        end_time_ms=int(turn["endTimeMs"]),
    )


def event_payload(event: DetectedEvent) -> dict[str, object]:
    return {
        "area": event.area.value,
        "type": event.type.value,
        "confidence": event.confidence.value,
        "timestampMs": event.timestamp_ms,
        "evidence": event.evidence,
        "evidenceTurnIds": list(event.evidence_turn_ids),
    }


def nudge_payload(nudge: LiveNudge) -> dict[str, object]:
    return {
        "area": nudge.area.value,
        "nudgeKey": nudge.nudge_key.value,
        "timestampMs": nudge.timestamp_ms,
    }


def reflection_instructions(
    stage: Literal["follow_up", "completion"],
    snapshot: CompletedMeetingSnapshot,
    report: PostMeetingReport,
    reflection_context: str,
    messages: list[dict[str, str]],
) -> str:
    stage_instruction = (
        "Ask one concise, specific follow-up question that helps the adviser notice something useful beyond repeating the report."
        if stage == "follow_up"
        else "Close the reflection warmly and provide one concise, practical adviser takeaway based on the adviser’s own intention. Also classify the takeaway using one canonical coaching area identifier, or null if no area can be identified."
    )
    return f"""You are a bounded private reflection coach for a financial adviser.
{stage_instruction}
Use only the selected focus, structured report, bounded generic reflection context, and reflection
messages below. Coach the adviser, not the customer. Do not provide financial advice, customer
summaries, customer quotations, names, scores, or rankings. Do not become a general chatbot.
Selected focus: {json.dumps([area.value for area in snapshot.selected_focus])}
Report: {report.model_dump_json()}
Reflection context: {reflection_context}
Reflection messages: {json.dumps(messages, ensure_ascii=False)}"""


def _session_or_404(session_id: str) -> PostMeetingSession:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "SESSION_NOT_FOUND", "message": "This meeting session is no longer available."},
        )
    return session


def _safe_ai_error(session_id: str, operation: str, error: Exception) -> None:
    logger.warning(
        "Post-meeting %s failed for session %s: %s",
        operation,
        session_id,
        type(error).__name__,
    )


@router.post("/post-meeting/{session_id}/report", response_model=ReportResponse)
async def create_report(session_id: str) -> ReportResponse:
    session = _session_or_404(session_id)
    async with session.lock:
        if session.report is not None:
            return ReportResponse(report=session.report, key_moment=key_moment_view(session))
        if not session.snapshot.turns:
            raise HTTPException(
                status_code=422,
                detail={"code": "NO_FINALIZED_TURNS", "message": "There was not enough finalized conversation to prepare feedback."},
            )
        try:
            generated = await get_ai_service().generate_report(session.snapshot)
        except Exception as error:
            _safe_ai_error(session_id, "report", error)
            raise HTTPException(
                status_code=503,
                detail={"code": "REPORT_UNAVAILABLE", "message": "Feedback could not be prepared. Please try again."},
            ) from None
        if store.get(session_id) is not session:
            raise HTTPException(
                status_code=410,
                detail={"code": "SESSION_EXPIRED", "message": "This meeting session has expired."},
            )
        session.report = PostMeetingReport.model_validate(
            generated.model_dump(
                exclude={"reflection_context", "strength_areas", "improvement_areas", "key_moment"}
            )
        )
        session.key_moment = generated.key_moment
        session.reflection_context = generated.reflection_context
        session.strength_areas = tuple(generated.strength_areas)
        session.improvement_areas = tuple(generated.improvement_areas)
        return ReportResponse(report=session.report, key_moment=key_moment_view(session))


@router.post("/post-meeting/{session_id}/reflection", response_model=ReflectionResponse)
async def create_reflection(session_id: str, request: ReflectionRequest) -> ReflectionResponse:
    session = _session_or_404(session_id)
    async with session.lock:
        previous = session.processed_reflection_requests.get(str(request.message_id))
        if previous is not None:
            return previous
        if session.report is None or session.reflection_context is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "REPORT_NOT_READY", "message": "Prepare the feedback report before reflecting."},
            )
        if session.reflection_reply_count >= 2:
            raise HTTPException(
                status_code=409,
                detail={"code": "REFLECTION_COMPLETE", "message": "This reflection is already complete."},
            )

        adviser_message = {"author": "advisor", "content": request.message}
        messages_for_model = [*session.reflection_messages, adviser_message]
        try:
            if session.reflection_reply_count == 0:
                generated = await get_ai_service().generate_reflection_follow_up(
                    session.snapshot,
                    session.report,
                    session.reflection_context,
                    messages_for_model,
                )
                response = ReflectionResponse(
                    coach_message=generated.coach_message,
                    complete=False,
                    takeaway=None,
                )
            else:
                generated = await get_ai_service().generate_reflection_completion(
                    session.snapshot,
                    session.report,
                    session.reflection_context,
                    messages_for_model,
                )
                response = ReflectionResponse(
                    coach_message=generated.coach_message,
                    complete=True,
                    takeaway=generated.takeaway,
                )
                session.takeaway_area = generated.takeaway_area
        except Exception as error:
            _safe_ai_error(session_id, "reflection", error)
            raise HTTPException(
                status_code=503,
                detail={"code": "REFLECTION_UNAVAILABLE", "message": "Reflection could not respond. Please try again."},
            ) from None

        if store.get(session_id) is not session:
            raise HTTPException(
                status_code=410,
                detail={"code": "SESSION_EXPIRED", "message": "This meeting session has expired."},
            )
        session.reflection_messages.extend(
            [adviser_message, {"author": "coach", "content": response.coach_message}]
        )
        session.processed_reflection_requests[str(request.message_id)] = response
        session.reflection_reply_count += 1
        return response


@router.delete("/post-meeting/{session_id}", status_code=204)
async def delete_post_meeting(session_id: str) -> None:
    store.delete(session_id)
