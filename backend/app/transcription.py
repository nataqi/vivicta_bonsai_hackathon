import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from deepgram import AsyncDeepgramClient
from deepgram.listen.v1.types.listen_v1results import ListenV1Results
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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

    def consume(self, result: Any) -> list[dict[str, Any]]:
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

                self._words.append(
                    _BufferedWord(
                        text=text,
                        start=word.start,
                        end=word.end,
                        speaker=speaker,
                    )
                )

        if result.speech_final or getattr(result, "from_finalize", False):
            return self.flush()
        return []

    def flush(self) -> list[dict[str, Any]]:
        if not self._words:
            return []

        groups: list[list[_BufferedWord]] = []
        for word in self._words:
            if not groups or groups[-1][-1].speaker != word.speaker:
                groups.append([word])
            else:
                groups[-1].append(word)

        turns = [self._make_turn(group) for group in groups]
        self._words = []
        return turns

    def _make_turn(self, words: list[_BufferedWord]) -> dict[str, Any]:
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
        return {
            "id": str(uuid4()),
            "speaker": "advisor" if speaker_label == self._advisor_label else "customer",
            "text": " ".join(word.text for word in words),
            "startTimeMs": start_time_ms,
            "endTimeMs": end_time_ms,
            "durationMs": max(0, end_time_ms - start_time_ms),
            "isFinal": True,
        }


async def _send_json(websocket: WebSocket, payload: dict[str, Any]) -> bool:
    try:
        await websocket.send_json(payload)
        return True
    except (RuntimeError, WebSocketDisconnect):
        return False


@router.websocket("/ws/transcription")
async def transcription_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    assembler = SpeakerTurnAssembler()
    browser_task: asyncio.Task[str] | None = None
    deepgram_task: asyncio.Task[None] | None = None

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
                        await _send_json(
                            websocket,
                            {"type": "error", "message": "Invalid control message."},
                        )
                        continue
                    if control.get("type") == "stop":
                        return "stop"

            async def receive_deepgram_results() -> None:
                async for result in connection:
                    if not isinstance(result, ListenV1Results):
                        continue

                    for turn in assembler.consume(result):
                        if not await _send_json(
                            websocket, {"type": "speaker_turn", "turn": turn}
                        ):
                            raise WebSocketDisconnect()

                    if result.from_finalize:
                        finalized.set()

            await websocket.send_json({"type": "session.ready"})
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

                for turn in assembler.flush():
                    await _send_json(
                        websocket, {"type": "speaker_turn", "turn": turn}
                    )
                await _send_json(websocket, {"type": "session.stopped"})
            else:
                await connection.send_finalize()
                await connection.send_close_stream()

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Live transcription session failed")
        await _send_json(
            websocket,
            {
                "type": "error",
                "message": "Live transcription stopped unexpectedly. Please try again.",
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
