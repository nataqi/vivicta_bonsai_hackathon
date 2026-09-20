from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import post_meeting
from app.coaching import CoachingArea

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_FOCUS = (
    CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES,
    CoachingArea.STAY_BEFORE_SOLVING,
)
HISTORY_LIMIT = 5
DEMO_ADVISER_ID = "demo-adviser"
DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "adviser_learning.db"


class LearningCandidate(BaseModel):
    """The only model allowed to cross into persistent storage."""

    model_config = ConfigDict(extra="forbid")

    record_id: UUID
    adviser_id: str
    focus_areas: list[CoachingArea] = Field(min_length=1, max_length=5)
    strength_areas: list[CoachingArea] = Field(default_factory=list, max_length=2)
    improvement_areas: list[CoachingArea] = Field(default_factory=list, max_length=2)
    takeaway_area: CoachingArea | None = None

    @field_validator("focus_areas", "strength_areas", "improvement_areas")
    @classmethod
    def unique_areas(cls, value: list[CoachingArea]) -> list[CoachingArea]:
        if len(set(value)) != len(value):
            raise ValueError("Coaching areas must be unique")
        return value


class LearningRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    adviser_id: str
    focus_areas: list[CoachingArea] = Field(min_length=1, max_length=5)
    strength_areas: list[CoachingArea] = Field(default_factory=list, max_length=2)
    improvement_areas: list[CoachingArea] = Field(default_factory=list, max_length=2)
    takeaway_area: CoachingArea | None = None
    created_at: datetime

    @field_validator("focus_areas", "strength_areas", "improvement_areas")
    @classmethod
    def unique_areas(cls, value: list[CoachingArea]) -> list[CoachingArea]:
        if len(set(value)) != len(value):
            raise ValueError("Coaching areas must be unique")
        return value


class FocusRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    focus_areas: list[CoachingArea] = Field(alias="focusAreas", min_length=1, max_length=5)

    @field_validator("focus_areas")
    @classmethod
    def unique_focus(cls, value: list[CoachingArea]) -> list[CoachingArea]:
        if len(set(value)) != len(value):
            raise ValueError("Focus areas must be unique")
        return value


class HomeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    focus_areas: list[CoachingArea] = Field(alias="focusAreas")
    recent_insight: str | None = Field(alias="recentInsight")
    history_state: str = Field(alias="historyState")


class CompletionResponse(BaseModel):
    learning_saved: bool = Field(alias="learningSaved")
    cleanup_complete: bool = Field(alias="cleanupComplete")


class SQLiteUnavailable(Exception):
    pass


@dataclass(frozen=True)
class HistoryResult:
    records: tuple[LearningRecord, ...]
    malformed: bool = False


def database_path() -> Path:
    override = os.getenv("ADVISER_LEARNING_DB_PATH", "").strip()
    return Path(override) if override else DEFAULT_DB_PATH


class SQLiteRepository:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else database_path()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=5)
            connection.row_factory = sqlite3.Row
            return connection
        except (OSError, sqlite3.Error) as error:
            raise SQLiteUnavailable() from error

    @contextmanager
    def connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        try:
            with self.connection() as connection:
                connection.executescript(
                    """
                    create table if not exists adviser_profiles (
                        id text primary key,
                        selected_focus text not null,
                        created_at text not null,
                        updated_at text not null
                    );
                    create table if not exists adviser_learning_history (
                        id text primary key,
                        adviser_id text not null,
                        focus_areas text not null,
                        strength_areas text not null,
                        improvement_areas text not null,
                        takeaway_area text,
                        created_at text not null
                    );
                    create index if not exists adviser_learning_history_recent_idx
                        on adviser_learning_history(adviser_id, created_at desc);
                    """
                )
        except (OSError, sqlite3.Error) as error:
            raise SQLiteUnavailable() from error

    def read_profile(self, adviser_id: str) -> list[CoachingArea] | None:
        try:
            with self.connection() as connection:
                row = connection.execute(
                    "select selected_focus from adviser_profiles where id = ?",
                    (adviser_id,),
                ).fetchone()
        except (OSError, sqlite3.Error) as error:
            raise SQLiteUnavailable() from error
        if row is None:
            return None
        try:
            return parse_areas(json.loads(row["selected_focus"]), min_length=1, max_length=5)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def read_history(self, adviser_id: str) -> HistoryResult:
        try:
            with self.connection() as connection:
                rows = connection.execute(
                    """
                    select id, adviser_id, focus_areas, strength_areas, improvement_areas,
                           takeaway_area, created_at
                    from adviser_learning_history
                    where adviser_id = ?
                    order by created_at desc
                    """,
                    (adviser_id,),
                )
                records: list[LearningRecord] = []
                malformed = False
                while len(records) < HISTORY_LIMIT:
                    batch = rows.fetchmany(HISTORY_LIMIT)
                    if not batch:
                        break
                    for row in batch:
                        try:
                            records.append(
                                LearningRecord(
                                    id=UUID(row["id"]),
                                    adviser_id=row["adviser_id"],
                                    focus_areas=parse_areas(json.loads(row["focus_areas"]), min_length=1, max_length=5),
                                    strength_areas=parse_areas(json.loads(row["strength_areas"]), min_length=0, max_length=2),
                                    improvement_areas=parse_areas(json.loads(row["improvement_areas"]), min_length=0, max_length=2),
                                    takeaway_area=CoachingArea(row["takeaway_area"]) if row["takeaway_area"] else None,
                                    created_at=datetime.fromisoformat(row["created_at"]),
                                )
                            )
                            if len(records) >= HISTORY_LIMIT:
                                break
                        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
                            malformed = True
                            logger.warning("Malformed adviser learning row ignored: %s", type(error).__name__)
                return HistoryResult(tuple(records), malformed=malformed)
        except (OSError, sqlite3.Error) as error:
            raise SQLiteUnavailable() from error

    def save_focus(self, adviser_id: str, focus_areas: list[CoachingArea]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        encoded = json.dumps([area.value for area in focus_areas], separators=(",", ":"))
        try:
            with self.connection() as connection:
                connection.execute(
                    """
                    insert into adviser_profiles(id, selected_focus, created_at, updated_at)
                    values (?, ?, ?, ?)
                    on conflict(id) do update set selected_focus = excluded.selected_focus,
                        updated_at = excluded.updated_at
                    """,
                    (adviser_id, encoded, now, now),
                )
        except (OSError, sqlite3.Error) as error:
            raise SQLiteUnavailable() from error

    def save(self, candidate: LearningCandidate) -> None:
        now = datetime.now(timezone.utc).isoformat()
        focus = json.dumps([area.value for area in candidate.focus_areas], separators=(",", ":"))
        strengths = json.dumps([area.value for area in candidate.strength_areas], separators=(",", ":"))
        improvements = json.dumps([area.value for area in candidate.improvement_areas], separators=(",", ":"))
        try:
            with self.connection() as connection:
                connection.execute(
                    """
                    insert into adviser_profiles(id, selected_focus, created_at, updated_at)
                    values (?, ?, ?, ?)
                    on conflict(id) do update set selected_focus = excluded.selected_focus,
                        updated_at = excluded.updated_at
                    """,
                    (candidate.adviser_id, focus, now, now),
                )
                connection.execute(
                    """
                    insert into adviser_learning_history(
                        id, adviser_id, focus_areas, strength_areas, improvement_areas,
                        takeaway_area, created_at
                    ) values (?, ?, ?, ?, ?, ?, ?)
                    on conflict(id) do update set
                        adviser_id = excluded.adviser_id,
                        focus_areas = excluded.focus_areas,
                        strength_areas = excluded.strength_areas,
                        improvement_areas = excluded.improvement_areas,
                        takeaway_area = excluded.takeaway_area
                    """,
                    (
                        str(candidate.record_id),
                        candidate.adviser_id,
                        focus,
                        strengths,
                        improvements,
                        candidate.takeaway_area.value if candidate.takeaway_area else None,
                        now,
                    ),
                )
        except (OSError, sqlite3.Error) as error:
            raise SQLiteUnavailable() from error


def parse_areas(value: object, *, min_length: int, max_length: int) -> list[CoachingArea]:
    if not isinstance(value, list) or not min_length <= len(value) <= max_length:
        raise ValueError("Invalid coaching area list")
    parsed = [CoachingArea(item) for item in value]
    if len(set(parsed)) != len(parsed):
        raise ValueError("Duplicate coaching area")
    return parsed


def repository() -> SQLiteRepository:
    return SQLiteRepository()


def insight_for_history(records: tuple[LearningRecord, ...]) -> str | None:
    if not records:
        return None
    current = records[0]
    prior = records[1:]
    prior_improvements = {area for row in prior for area in row.improvement_areas}
    prior_strengths = {area for row in prior for area in row.strength_areas}
    repeated = next((area for area in current.improvement_areas if area in prior_improvements), None)
    progressed = next((area for area in current.strength_areas if area in prior_improvements), None)
    stable = next((area for area in current.strength_areas if area in prior_strengths), None)
    area = repeated or progressed or stable
    if repeated:
        return f"{area_label(area)} remains a useful area to practise."
    if progressed:
        return f"You’re showing more consistency with {area_label(area)}."
    if stable:
        return f"{area_label(area)} is becoming a steady strength."
    if current.improvement_areas:
        return f"Keep practising {area_label(current.improvement_areas[0])}."
    if current.strength_areas:
        return f"Your recent session showed a strength in {area_label(current.strength_areas[0])}."
    return "Keep noticing which coaching dimension helps you stay present."


def area_label(area: CoachingArea | None) -> str:
    return {
        CoachingArea.PACE_AND_PAUSES: "a calm pace and well-timed pauses",
        CoachingArea.TURN_TAKING_AND_INTERRUPTS: "turn-taking",
        CoachingArea.OPEN_QUESTIONS: "open questions",
        CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES: "acknowledging emotional cues",
        CoachingArea.STAY_BEFORE_SOLVING: "staying with the customer before solving",
    }.get(area, "the coaching dimensions")


def build_candidate(session: post_meeting.PostMeetingSession) -> LearningCandidate | None:
    if session.report is None:
        return None
    return LearningCandidate(
        record_id=UUID(session.snapshot.session_id),
        adviser_id=DEMO_ADVISER_ID,
        focus_areas=list(session.snapshot.selected_focus) or list(DEFAULT_FOCUS),
        strength_areas=list(session.strength_areas),
        improvement_areas=list(session.improvement_areas),
        takeaway_area=session.takeaway_area,
    )


@router.get("/adviser-learning/home", response_model=HomeResponse)
async def adviser_home() -> HomeResponse:
    try:
        store = repository()
        focus = store.read_profile(DEMO_ADVISER_ID) or list(DEFAULT_FOCUS)
        history = store.read_history(DEMO_ADVISER_ID)
    except SQLiteUnavailable:
        return HomeResponse(focusAreas=list(DEFAULT_FOCUS), recentInsight=None, historyState="unavailable")
    if history.malformed and not history.records:
        return HomeResponse(focusAreas=focus, recentInsight=None, historyState="unavailable")
    return HomeResponse(
        focusAreas=focus,
        recentInsight=insight_for_history(history.records),
        historyState="ready" if history.records else "empty",
    )


@router.put("/adviser-learning/focus", response_model=HomeResponse)
async def save_focus(request: FocusRequest) -> HomeResponse:
    try:
        repository().save_focus(DEMO_ADVISER_ID, request.focus_areas)
    except SQLiteUnavailable:
        raise HTTPException(
            status_code=503,
            detail={"code": "LEARNING_UNAVAILABLE", "message": "Focus could not be saved right now."},
        ) from None
    return HomeResponse(focusAreas=request.focus_areas, recentInsight=None, historyState="empty")


@router.post("/post-meeting/{session_id}/complete", response_model=CompletionResponse)
async def complete_post_meeting(session_id: str) -> CompletionResponse:
    session = post_meeting.store.get(session_id)
    if session is None:
        return CompletionResponse(learningSaved=False, cleanupComplete=True)
    saved = False
    try:
        async with session.lock:
            candidate = build_candidate(session)
            if candidate is not None:
                try:
                    repository().save(candidate)
                    saved = True
                except SQLiteUnavailable:
                    logger.warning("Adviser learning persistence unavailable")
    except Exception as error:
        logger.warning("Adviser learning completion failed: %s", type(error).__name__)
    finally:
        post_meeting.store.delete(session_id)
    return CompletionResponse(learningSaved=saved, cleanupComplete=True)
