import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import uuid4

from deepgram import AsyncDeepgramClient
from deepgram.listen.v1.types.listen_v1results import ListenV1Results
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.coaching import CoachingSession, LiveNudge, TimedWord, TurnObservation
from app.post_meeting import store as post_meeting_store
from app.semantic_analysis import OpenRouterSemanticAnalyzer

router = APIRouter()
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _BufferedWord:
    text: str
    start: float
    end: float
    speaker: int


class SpeakerTurnAssembler:
    """Build finalized application turns from Deepgram result messages."""

    def __init__(self) -> None:
        self._words: list[_BufferedWord] = []
        self._advisor_label: int | None = None
        self._seen_labels: set[int] = set()
        self._pending_id: str | None = None

    def consume(self, result: Any) -> list[dict[str, Any]]:
        return [observation.turn for observation in self.consume_observations(result)]

    def consume_observations(self, result: Any) -> list[TurnObservation]:
        if not result.is_final:
            return []

        alternatives = getattr(result.channel, "alternatives", [])
        if alternatives:
            for word in alternatives[0].words:
                text = (word.punctuated_word or word.word).strip()
                if not text:
                    continue

                speaker = word.speaker
                if speaker is None:
                    speaker = self._words[-1].speaker if self._words else 0

                if not self._words:
                    self._pending_id = str(uuid4())

                self._words.append(
                    _BufferedWord(
                        text=text,
                        start=word.start,
                        end=word.end,
                        speaker=speaker,
                    )
                )

        if result.speech_final or getattr(result, "from_finalize", False):
            return self.flush_observations()
        return []

    def preview_observation(self) -> TurnObservation | None:
        """The still-accumulating turn, for live display only (never fed to coaching)."""

        if not self._words:
            return None
        groups = self._grouped_words()
        return self._make_observation(groups[-1], turn_id=self._pending_id, is_final=False)

    def flush(self) -> list[dict[str, Any]]:
        return [observation.turn for observation in self.flush_observations()]

    def flush_observations(self) -> list[TurnObservation]:
        if not self._words:
            return []

        groups = self._grouped_words()
        last_index = len(groups) - 1
        turns = [
            self._make_observation(
                group,
                turn_id=self._pending_id if index == last_index else None,
            )
            for index, group in enumerate(groups)
        ]
        self._words = []
        self._pending_id = None
        return turns

    def _grouped_words(self) -> list[list[_BufferedWord]]:
        groups: list[list[_BufferedWord]] = []
        for word in self._words:
            if not groups or groups[-1][-1].speaker != word.speaker:
                groups.append([word])
            else:
                groups[-1].append(word)
        return groups

    def _make_observation(
        self,
        words: list[_BufferedWord],
        *,
        turn_id: str | None = None,
        is_final: bool = True,
    ) -> TurnObservation:
        speaker_label = words[0].speaker
        if self._advisor_label is None:
            self._advisor_label = speaker_label

        self._seen_labels.add(speaker_label)
        if len(self._seen_labels) > 2:
            logger.warning(
                "Deepgram returned more than two speaker labels for a two-person session"
            )

        start_time_ms = round(words[0].start * 1000)
        end_time_ms = round(words[-1].end * 1000)
        turn = {
            "id": turn_id or str(uuid4()),
            "speaker": "advisor" if speaker_label == self._advisor_label else "customer",
            "text": " ".join(word.text for word in words),
            "startTimeMs": start_time_ms,
            "endTimeMs": end_time_ms,
            "durationMs": max(0, end_time_ms - start_time_ms),
            "isFinal": is_final,
        }
        return TurnObservation(
            turn=turn,
            words=tuple(
                TimedWord(
                    word.text,
                    round(word.start * 1000),
                    round(word.end * 1000),
                )
                for word in words
            ),
        )


class ReflectionTranscriptAssembler:
    """Collect final, single-speaker Deepgram segments for reflection dictation."""

    def __init__(self) -> None:
        self._segments: list[str] = []

    def consume(self, result: Any) -> None:
        if not result.is_final:
            return
        alternatives = getattr(result.channel, "alternatives", [])
        if not alternatives:
            return
        transcript = str(getattr(alternatives[0], "transcript", "")).strip()
        if transcript:
            self._segments.append(transcript)

    def text(self) -> str:
        return " ".join(self._segments).strip()


async def _send_json(websocket: WebSocket, payload: dict[str, Any]) -> bool:
    try:
        await websocket.send_json(payload)
        return True
    except (RuntimeError, WebSocketDisconnect):
        return False


async def emit_coached_observation(
    observation: TurnObservation,
    coaching: CoachingSession,
    send: Callable[[dict[str, Any]], Awaitable[bool]],
) -> None:
    if not await send({"type": "speaker_turn", "turn": observation.turn}):
        raise WebSocketDisconnect()

    async def send_nudge(nudge: LiveNudge) -> None:
        await send({"type": "live_nudge", "nudge": nudge.to_payload()})

    nudge = coaching.observe(observation)
    if nudge:
        await send_nudge(nudge)
    coaching.schedule_semantic(send_nudge)


@router.websocket("/ws/transcription")
async def transcription_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    session_id = str(uuid4())
    assembler = SpeakerTurnAssembler()
    coaching = CoachingSession(OpenRouterSemanticAnalyzer.from_environment())
    browser_task: asyncio.Task[str] | None = None
    deepgram_task: asyncio.Task[None] | None = None
    send_lock = asyncio.Lock()

    async def send(payload: dict[str, Any]) -> bool:
        async with send_lock:
            return await _send_json(websocket, payload)

    try:
        deepgram = AsyncDeepgramClient(api_key=os.environ["DEEPGRAM_API_KEY"])
        async with deepgram.listen.v1.connect(
            model="nova-3",
            language="en-US",
            diarize_model="latest",
            channels=1,
            interim_results=True,
            endpointing=500,
            punctuate=True,
            mip_opt_out=True,
        ) as connection:
            finalized = asyncio.Event()

            async def receive_browser_audio() -> str:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return "disconnect"

                    audio = message.get("bytes")
                    if audio:
                        await connection.send_media(audio)
                        continue

                    text = message.get("text")
                    if not text:
                        continue
                    try:
                        control = json.loads(text)
                    except json.JSONDecodeError:
                        await send(
                            {"type": "error", "message": "Invalid control message."},
                        )
                        continue
                    if control.get("type") == "session.configure":
                        focus_areas = control.get("focusAreas", [])
                        if isinstance(focus_areas, list):
                            coaching.set_focus(
                                [value for value in focus_areas if isinstance(value, str)]
                            )
                        continue
                    if control.get("type") == "stop":
                        return "stop"

            async def receive_deepgram_results() -> None:
                async for result in connection:
                    if not isinstance(result, ListenV1Results):
                        continue

                    flushed = assembler.consume_observations(result)
                    if flushed:
                        for observation in flushed:
                            await emit_coached_observation(observation, coaching, send)
                    else:
                        preview = assembler.preview_observation()
                        if preview:
                            await send({"type": "speaker_turn", "turn": preview.turn})

                    if result.from_finalize:
                        finalized.set()

            await send({"type": "session.ready", "sessionId": session_id})
            browser_task = asyncio.create_task(receive_browser_audio())
            deepgram_task = asyncio.create_task(receive_deepgram_results())

            done, _ = await asyncio.wait(
                {browser_task, deepgram_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if deepgram_task in done:
                exception = deepgram_task.exception()
                if exception:
                    raise exception
                raise RuntimeError("Deepgram stream closed unexpectedly")

            reason = browser_task.result()
            if reason == "stop":
                await connection.send_finalize()
                try:
                    await asyncio.wait_for(finalized.wait(), timeout=2.0)
                except TimeoutError:
                    pass

                await connection.send_close_stream()
                try:
                    await asyncio.wait_for(asyncio.shield(deepgram_task), timeout=1.0)
                except TimeoutError:
                    deepgram_task.cancel()

                for observation in assembler.flush_observations():
                    await emit_coached_observation(observation, coaching, send)
                completed_data = await coaching.freeze()
                post_meeting_store.register(session_id, completed_data)
                await send({"type": "session.stopped", "sessionId": session_id})
            else:
                await connection.send_finalize()
                await connection.send_close_stream()

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Live transcription session failed")
        await send(
            {
                "type": "error",
                "message": "Live transcription stopped unexpectedly. Please try again.",
            },
        )
    finally:
        await coaching.close()
        pending_tasks: list[asyncio.Task[Any]] = []
        for task in (browser_task, deepgram_task):
            if task is not None and not task.done():
                task.cancel()
                pending_tasks.append(task)
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        try:
            await websocket.close()
        except RuntimeError:
            pass


@router.websocket("/ws/reflection-dictation")
async def reflection_dictation_websocket(websocket: WebSocket) -> None:
    """Transcribe one temporary adviser dictation without coaching or persistence."""
    await websocket.accept()
    browser_task: asyncio.Task[str] | None = None
    deepgram_task: asyncio.Task[None] | None = None
    send_lock = asyncio.Lock()

    async def send(payload: dict[str, Any]) -> bool:
        async with send_lock:
            return await _send_json(websocket, payload)

    try:
        deepgram = AsyncDeepgramClient(api_key=os.environ["DEEPGRAM_API_KEY"])
        async with deepgram.listen.v1.connect(
            model="nova-3",
            language="en-US",
            channels=1,
            interim_results=True,
            endpointing=500,
            punctuate=True,
            mip_opt_out=True,
        ) as connection:
            assembler = ReflectionTranscriptAssembler()
            finalized = asyncio.Event()

            async def receive_browser_audio() -> str:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return "disconnect"
                    audio = message.get("bytes")
                    if audio:
                        await connection.send_media(audio)
                        continue
                    text = message.get("text")
                    if not text:
                        continue
                    try:
                        control = json.loads(text)
                    except json.JSONDecodeError:
                        await send({"type": "error", "message": "Invalid control message."})
                        continue
                    if control.get("type") == "stop":
                        return "stop"

            async def receive_deepgram_results() -> None:
                async for result in connection:
                    if not isinstance(result, ListenV1Results):
                        continue
                    assembler.consume(result)
                    if result.from_finalize:
                        finalized.set()

            await send({"type": "session.ready"})
            browser_task = asyncio.create_task(receive_browser_audio())
            deepgram_task = asyncio.create_task(receive_deepgram_results())
            done, _ = await asyncio.wait(
                {browser_task, deepgram_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if deepgram_task in done:
                exception = deepgram_task.exception()
                if exception:
                    raise exception
                raise RuntimeError("Deepgram stream closed unexpectedly")

            if browser_task.result() == "stop":
                await connection.send_finalize()
                try:
                    await asyncio.wait_for(finalized.wait(), timeout=2.0)
                except TimeoutError:
                    pass
                await connection.send_close_stream()
                try:
                    await asyncio.wait_for(asyncio.shield(deepgram_task), timeout=1.0)
                except TimeoutError:
                    deepgram_task.cancel()
                await send({"type": "transcript", "text": assembler.text()})
            else:
                await connection.send_finalize()
                await connection.send_close_stream()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Reflection dictation failed")
        await send(
            {
                "type": "error",
                "message": "Reflection dictation stopped unexpectedly. Please try again.",
            },
        )
    finally:
        pending_tasks: list[asyncio.Task[Any]] = []
        for task in (browser_task, deepgram_task):
            if task is not None and not task.done():
                task.cancel()
                pending_tasks.append(task)
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        try:
            await websocket.close()
        except RuntimeError:
            pass
