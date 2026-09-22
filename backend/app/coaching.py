import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Awaitable, Callable, Protocol

logger = logging.getLogger(__name__)


class CoachingArea(StrEnum):
    PACE_AND_PAUSES = "pace_and_pauses"
    TURN_TAKING_AND_INTERRUPTS = "turn_taking_and_interruptions"
    OPEN_QUESTIONS = "open_questions"
    ACKNOWLEDGING_EMOTIONAL_CUES = "acknowledging_emotional_cues"
    STAY_BEFORE_SOLVING = "stay_before_solving"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EventType(StrEnum):
    FAST_PACE = "FAST_PACE"
    LONG_MONOLOGUE = "LONG_MONOLOGUE"
    SHORT_RESPONSE_GAP = "SHORT_RESPONSE_GAP"
    INTERRUPTION_PATTERN = "INTERRUPTION_PATTERN"
    TALK_TIME_IMBALANCE = "TALK_TIME_IMBALANCE"
    CLOSED_QUESTION_PATTERN = "CLOSED_QUESTION_PATTERN"
    CUSTOMER_EMOTIONAL_CUE = "CUSTOMER_EMOTIONAL_CUE"
    MISSED_EMOTIONAL_CUE = "MISSED_EMOTIONAL_CUE"
    PREMATURE_PROBLEM_SOLVING = "PREMATURE_PROBLEM_SOLVING"


class NudgeKey(StrEnum):
    PACE_SLOW_DOWN = "PACE_SLOW_DOWN"
    ALLOW_PAUSE = "ALLOW_PAUSE"
    DO_NOT_INTERRUPT = "DO_NOT_INTERRUPT"
    ASK_OPEN_QUESTION = "ASK_OPEN_QUESTION"
    ACKNOWLEDGE_EMOTION = "ACKNOWLEDGE_EMOTION"
    STAY_BEFORE_SOLVING = "STAY_BEFORE_SOLVING"


NUDGE_TEXT = {
    NudgeKey.PACE_SLOW_DOWN: "Slow down a little.",
    NudgeKey.ALLOW_PAUSE: "Give the customer a moment.",
    NudgeKey.DO_NOT_INTERRUPT: "Let them finish.",
    NudgeKey.ASK_OPEN_QUESTION: "Try an open question.",
    NudgeKey.ACKNOWLEDGE_EMOTION: "Acknowledge what they just shared.",
    NudgeKey.STAY_BEFORE_SOLVING: "Stay with the moment before solving.",
}

EVENT_NUDGES = {
    EventType.FAST_PACE: NudgeKey.PACE_SLOW_DOWN,
    EventType.INTERRUPTION_PATTERN: NudgeKey.DO_NOT_INTERRUPT,
    EventType.CLOSED_QUESTION_PATTERN: NudgeKey.ASK_OPEN_QUESTION,
    EventType.MISSED_EMOTIONAL_CUE: NudgeKey.ACKNOWLEDGE_EMOTION,
    EventType.PREMATURE_PROBLEM_SOLVING: NudgeKey.STAY_BEFORE_SOLVING,
}

RELEVANCE_WINDOW_MS = 120_000


@dataclass(frozen=True)
class TimedWord:
    text: str
    start_time_ms: int
    end_time_ms: int


@dataclass(frozen=True)
class TurnObservation:
    turn: dict[str, object]
    words: tuple[TimedWord, ...]


@dataclass(frozen=True)
class DetectedEvent:
    area: CoachingArea
    type: EventType
    confidence: Confidence
    timestamp_ms: int
    evidence: str
    evidence_turn_ids: tuple[str, ...] = ()
    nudge_key: NudgeKey | None = None


@dataclass(frozen=True)
class LiveNudge:
    area: CoachingArea
    nudge_key: NudgeKey
    text: str
    timestamp_ms: int

    def to_payload(self) -> dict[str, object]:
        return {
            "area": self.area.value,
            "nudgeKey": self.nudge_key.value,
            "text": self.text,
            "timestampMs": self.timestamp_ms,
        }


@dataclass(frozen=True)
class ContextSnapshot:
    version: int
    turns: tuple[dict[str, object], ...]
    events: tuple[DetectedEvent, ...]
    nudges: tuple[LiveNudge, ...]
    selected_focus: tuple[CoachingArea, ...]
    summary: str


@dataclass(frozen=True)
class CompletedMeetingData:
    """Immutable meeting-scoped data handed to the post-meeting flow."""

    turns: tuple[dict[str, object], ...]
    selected_focus: tuple[CoachingArea, ...]
    events: tuple[DetectedEvent, ...]
    nudges: tuple[LiveNudge, ...]


class SemanticAnalyzer(Protocol):
    async def analyze(self, snapshot: ContextSnapshot) -> tuple[str, list[DetectedEvent]]: ...


class BehavioralAnalyzer:
    def __init__(self) -> None:
        self._previous: TurnObservation | None = None
        self._interruptions: deque[int] = deque()
        self._talk_time: deque[tuple[int, int, str, int]] = deque()

    def analyze(self, observation: TurnObservation) -> list[DetectedEvent]:
        turn = observation.turn
        speaker = turn["speaker"]
        end_ms = int(turn["endTimeMs"])
        turn_id = str(turn["id"])
        events: list[DetectedEvent] = []
        active_speech_ms = sum(
            max(0, word.end_time_ms - word.start_time_ms)
            for word in observation.words
        )
        self._talk_time.append(
            (int(turn["startTimeMs"]), end_ms, str(speaker), active_speech_ms)
        )
        while self._talk_time and end_ms - self._talk_time[0][1] > RELEVANCE_WINDOW_MS:
            self._talk_time.popleft()

        if speaker == "advisor" and observation.words:
            span_ms = (
                max(word.end_time_ms for word in observation.words)
                - min(word.start_time_ms for word in observation.words)
            )
            if span_ms > 0:
                wpm = len(observation.words) * 60_000 / span_ms
                if wpm >= 175 and span_ms >= 3_000:
                    confidence = Confidence.HIGH
                elif wpm >= 175 and span_ms >= 2_000:
                    confidence = Confidence.MEDIUM
                elif wpm >= 170:
                    confidence = Confidence.LOW
                else:
                    confidence = None
                if confidence:
                    events.append(
                        DetectedEvent(
                            CoachingArea.PACE_AND_PAUSES,
                            EventType.FAST_PACE,
                            confidence,
                            end_ms,
                            "Adviser speaking pace was sustained above the MVP threshold.",
                            (turn_id,),
                        )
                    )

            duration_ms = int(turn["durationMs"])
            if duration_ms >= 30_000:
                events.append(
                    DetectedEvent(
                        CoachingArea.TURN_TAKING_AND_INTERRUPTS,
                        EventType.LONG_MONOLOGUE,
                        Confidence.HIGH if duration_ms >= 45_000 else Confidence.MEDIUM,
                        end_ms,
                        "A continuous adviser turn was unusually long.",
                        (turn_id,),
                    )
                )

        if self._talk_time and end_ms - self._talk_time[0][0] >= 60_000:
            advisor_ms = sum(item[3] for item in self._talk_time if item[2] == "advisor")
            total_ms = sum(item[3] for item in self._talk_time)
            if total_ms and advisor_ms / total_ms > 0.70:
                events.append(
                    DetectedEvent(
                        CoachingArea.TURN_TAKING_AND_INTERRUPTS,
                        EventType.TALK_TIME_IMBALANCE,
                        Confidence.MEDIUM,
                        end_ms,
                        "Adviser talk time exceeded 70% of the recent window.",
                        (turn_id,),
                    )
                )

        previous = self._previous
        if previous and speaker == "advisor" and previous.turn["speaker"] == "customer":
            gap_ms = int(turn["startTimeMs"]) - int(previous.turn["endTimeMs"])
            if gap_ms < 600:
                events.append(
                    DetectedEvent(
                        CoachingArea.PACE_AND_PAUSES,
                        EventType.SHORT_RESPONSE_GAP,
                        Confidence.MEDIUM,
                        end_ms,
                        "The adviser responded with less than a 600 ms gap.",
                        (str(previous.turn["id"]), turn_id),
                    )
                )
            overlap_ms = -gap_ms
            if overlap_ms >= 300:
                self._interruptions.append(end_ms)
                while (
                    self._interruptions
                    and end_ms - self._interruptions[0] > RELEVANCE_WINDOW_MS
                ):
                    self._interruptions.popleft()
                events.append(
                    DetectedEvent(
                        CoachingArea.TURN_TAKING_AND_INTERRUPTS,
                        EventType.INTERRUPTION_PATTERN,
                        Confidence.HIGH if len(self._interruptions) >= 2 else Confidence.MEDIUM,
                        end_ms,
                        "Adviser speech overlapped customer speech.",
                        (str(previous.turn["id"]), turn_id),
                    )
                )

        self._previous = observation
        return events


@dataclass
class RollingContext:
    selected_focus: set[CoachingArea] = field(default_factory=set)
    summary: str = ""
    version: int = 0
    turns: deque[dict[str, object]] = field(default_factory=lambda: deque(maxlen=8))
    events: deque[DetectedEvent] = field(default_factory=lambda: deque(maxlen=8))
    nudges: deque[LiveNudge] = field(default_factory=lambda: deque(maxlen=3))

    def add_turn(self, turn: dict[str, object]) -> None:
        self.turns.append(turn)
        while sum(len(str(item["text"])) for item in self.turns) > 1_200:
            self.turns.popleft()
        self.version += 1
        self._prune_events(int(turn["endTimeMs"]))

    def add_events(self, events: list[DetectedEvent]) -> None:
        self.events.extend(events)
        if self.turns:
            self._prune_events(int(self.turns[-1]["endTimeMs"]))

    def _prune_events(self, now_ms: int) -> None:
        self.events = deque(
            (
                event
                for event in self.events
                if now_ms - event.timestamp_ms <= RELEVANCE_WINDOW_MS
            ),
            maxlen=8,
        )

    def snapshot(self) -> ContextSnapshot:
        if self.turns:
            self._prune_events(int(self.turns[-1]["endTimeMs"]))
        return ContextSnapshot(
            self.version,
            tuple(self.turns),
            tuple(self.events),
            tuple(self.nudges),
            tuple(sorted(self.selected_focus, key=lambda area: area.value)),
            self.summary[:300],
        )


class NudgeDecider:
    def __init__(self, global_cooldown_ms: int = 5_000, repeat_ms: int = 180_000) -> None:
        self.global_cooldown_ms = global_cooldown_ms
        self.repeat_ms = repeat_ms
        self.last_nudge_ms: int | None = None
        self.last_by_key: dict[NudgeKey, int] = {}

    def decide(
        self,
        events: list[DetectedEvent],
        selected_focus: set[CoachingArea],
    ) -> LiveNudge | None:
        candidates = []
        for event in events:
            if event.confidence != Confidence.HIGH:
                continue
            expected_key = EVENT_NUDGES.get(event.type)
            if expected_key is None:
                continue
            if event.nudge_key is not None and event.nudge_key != expected_key:
                continue
            candidates.append(event)
        candidates.sort(
            key=lambda event: (event.area in selected_focus, event.timestamp_ms),
            reverse=True,
        )
        for event in candidates:
            key = EVENT_NUDGES[event.type]
            if self.last_nudge_ms is not None and event.timestamp_ms - self.last_nudge_ms < self.global_cooldown_ms:
                continue
            last_same = self.last_by_key.get(key)
            if last_same is not None and event.timestamp_ms - last_same < self.repeat_ms:
                continue
            nudge = LiveNudge(event.area, key, NUDGE_TEXT[key], event.timestamp_ms)
            self.last_nudge_ms = event.timestamp_ms
            self.last_by_key[key] = event.timestamp_ms
            return nudge
        return None


class CoachingSession:
    def __init__(self, semantic_analyzer: SemanticAnalyzer | None = None) -> None:
        self.context = RollingContext()
        self.behavior = BehavioralAnalyzer()
        self.decider = NudgeDecider()
        self.semantic_analyzer = semantic_analyzer
        self._pending: ContextSnapshot | None = None
        self._worker: asyncio.Task[None] | None = None
        self._closed = False
        self._meeting_turns: list[dict[str, object]] = []
        self._meeting_events: list[DetectedEvent] = []
        self._meeting_nudges: list[LiveNudge] = []

    def set_focus(self, values: list[str]) -> None:
        self.context.selected_focus = {
            CoachingArea(value) for value in values if value in CoachingArea._value2member_map_
        }

    def observe(self, observation: TurnObservation) -> LiveNudge | None:
        if self._closed:
            return None
        self._meeting_turns.append(dict(observation.turn))
        self.context.add_turn(observation.turn)
        events = self.behavior.analyze(observation)
        self._meeting_events.extend(events)
        self.context.add_events(events)
        nudge = self.decider.decide(events, self.context.selected_focus)
        if nudge:
            self.context.nudges.append(nudge)
            self._meeting_nudges.append(nudge)
        return nudge

    def schedule_semantic(
        self, on_nudge: Callable[[LiveNudge], Awaitable[None]]
    ) -> None:
        if self.semantic_analyzer is None or self._closed:
            return
        self._pending = self.context.snapshot()
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._semantic_loop(on_nudge))

    async def _semantic_loop(
        self, on_nudge: Callable[[LiveNudge], Awaitable[None]]
    ) -> None:
        while self._pending is not None and not self._closed:
            snapshot = self._pending
            self._pending = None
            try:
                summary, events = await self.semantic_analyzer.analyze(snapshot)
            except Exception as error:
                logger.warning("Live semantic analysis skipped: %s", type(error).__name__)
                continue
            if self._closed:
                return
            if self.context.version - snapshot.version > 1:
                continue
            self.context.summary = summary[:300]
            self._meeting_events.extend(events)
            self.context.add_events(events)
            nudge = self.decider.decide(events, self.context.selected_focus)
            if nudge:
                self.context.nudges.append(nudge)
                self._meeting_nudges.append(nudge)
                await on_nudge(nudge)

    async def freeze(self) -> CompletedMeetingData:
        """Close live work, then return a detached immutable meeting snapshot."""

        await self.close()
        return CompletedMeetingData(
            turns=tuple(dict(turn) for turn in self._meeting_turns),
            selected_focus=tuple(
                sorted(self.context.selected_focus, key=lambda area: area.value)
            ),
            events=tuple(self._meeting_events),
            nudges=tuple(self._meeting_nudges),
        )

    async def close(self) -> None:
        self._closed = True
        self._pending = None
        if self._worker and not self._worker.done():
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
