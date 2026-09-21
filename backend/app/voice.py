from __future__ import annotations

import asyncio
import logging
import os
from typing import Protocol

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from app import post_meeting

logger = logging.getLogger(__name__)
router = APIRouter()

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
ELEVENLABS_TTS_MODEL = "eleven_multilingual_v2"
# ElevenLabs premade voice ("Sarah"), used when the adviser's own voice cannot be cloned.
# Premade voices work on every plan; library voices such as "Rachel" are blocked on the free plan.
DEFAULT_NEUTRAL_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
REQUEST_TIMEOUT_SECONDS = 30.0

# The browser sends 16 kHz mono 16-bit WAV, which is 32,000 bytes per second.
WAV_BYTES_PER_SECOND = 32_000
MIN_SAMPLE_SECONDS = 8
MIN_SAMPLE_BYTES = MIN_SAMPLE_SECONDS * WAV_BYTES_PER_SECOND
MAX_SAMPLE_BYTES = 4 * 1024 * 1024


class VoiceProviderError(Exception):
    pass


class VoiceProvider(Protocol):
    async def clone_voice(self, name: str, sample_wav: bytes) -> str: ...

    async def speak(self, voice_id: str, text: str) -> bytes: ...

    async def delete_voice(self, voice_id: str) -> None: ...


class ElevenLabsProvider:
    def __init__(self, api_key: str) -> None:
        self._headers = {"xi-api-key": api_key}

    async def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.request(
                    method,
                    f"{ELEVENLABS_BASE_URL}{path}",
                    headers=self._headers,
                    **kwargs,
                )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise VoiceProviderError(type(error).__name__) from None
        return response

    async def clone_voice(self, name: str, sample_wav: bytes) -> str:
        response = await self._request(
            "POST",
            "/voices/add",
            data={"name": name, "remove_background_noise": "true"},
            files=[("files", ("adviser-sample.wav", sample_wav, "audio/wav"))],
        )
        voice_id = response.json().get("voice_id")
        if not isinstance(voice_id, str) or not voice_id:
            raise VoiceProviderError("No voice id returned")
        return voice_id

    async def speak(self, voice_id: str, text: str) -> bytes:
        response = await self._request(
            "POST",
            f"/text-to-speech/{voice_id}",
            params={"output_format": "mp3_44100_128"},
            json={"text": text, "model_id": ELEVENLABS_TTS_MODEL},
        )
        return response.content

    async def delete_voice(self, voice_id: str) -> None:
        await self._request("DELETE", f"/voices/{voice_id}")


_provider: VoiceProvider | None = None


def get_provider() -> VoiceProvider | None:
    global _provider
    if _provider is None:
        api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        if api_key:
            _provider = ElevenLabsProvider(api_key)
    return _provider


def neutral_voice_id() -> str:
    return os.getenv("ELEVENLABS_NEUTRAL_VOICE_ID", "").strip() or DEFAULT_NEUTRAL_VOICE_ID


_background_tasks: set[asyncio.Task[None]] = set()


async def _delete_quietly(voice_id: str) -> None:
    provider = get_provider()
    if provider is None:
        return
    try:
        await provider.delete_voice(voice_id)
    except Exception as error:
        logger.warning("Provider voice deletion failed: %s", type(error).__name__)


def _schedule_voice_deletion(voice_id: str) -> None:
    """Safety net for sessions dropped by expiry, completion, or cleanup."""
    try:
        task = asyncio.get_running_loop().create_task(_delete_quietly(voice_id))
    except RuntimeError:
        logger.warning("Provider voice could not be scheduled for deletion")
        return
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


post_meeting.store.voice_discard_hook = _schedule_voice_deletion


@router.post("/post-meeting/{session_id}/voice/better-take")
async def better_take(session_id: str, request: Request) -> Response:
    """Speak the report's better answer, in a temporary clone of the adviser's voice if possible."""
    session = post_meeting._session_or_404(session_id)
    moment = session.key_moment
    if moment is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "NO_KEY_MOMENT", "message": "There is no key moment to replay."},
        )
    provider = get_provider()
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "VOICE_UNAVAILABLE", "message": "Voice playback is not configured."},
        )
    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit() and int(declared_length) > MAX_SAMPLE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "SAMPLE_TOO_LARGE", "message": "The voice sample was too large."},
        )
    sample = await request.body()
    if len(sample) > MAX_SAMPLE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "SAMPLE_TOO_LARGE", "message": "The voice sample was too large."},
        )

    async with session.voice_lock:
        mode = "neutral"
        voice_id = neutral_voice_id()
        if session.voice_id:
            voice_id, mode = session.voice_id, "cloned"
        elif len(sample) >= MIN_SAMPLE_BYTES:
            try:
                cloned_id = await provider.clone_voice(f"coach-{session_id[:8]}", sample)
            except Exception as error:
                logger.warning("Voice cloning failed for session %s: %s", session_id, type(error).__name__)
            else:
                if post_meeting.store.get(session_id) is not session:
                    await _delete_quietly(cloned_id)
                    raise HTTPException(
                        status_code=410,
                        detail={"code": "SESSION_EXPIRED", "message": "This meeting session has expired."},
                    )
                session.voice_id = cloned_id
                voice_id, mode = cloned_id, "cloned"
        try:
            audio = await provider.speak(voice_id, moment.better_answer)
        except Exception as error:
            logger.warning("Voice synthesis failed for session %s: %s", session_id, type(error).__name__)
            raise HTTPException(
                status_code=503,
                detail={"code": "VOICE_UNAVAILABLE", "message": "The better take could not be voiced. Please try again."},
            ) from None
    return Response(content=audio, media_type="audio/mpeg", headers={"X-Voice-Mode": mode})


@router.delete("/post-meeting/{session_id}/voice")
async def delete_voice(session_id: str) -> dict[str, bool]:
    """Delete the provider-side cloned voice now and report whether that is confirmed."""
    session = post_meeting.store.get(session_id)
    if session is None:
        return {"hadVoice": False, "voiceDeleted": False}
    async with session.voice_lock:
        voice_id = session.voice_id
        if not voice_id:
            return {"hadVoice": False, "voiceDeleted": True}
        provider = get_provider()
        if provider is None:
            return {"hadVoice": True, "voiceDeleted": False}
        try:
            await provider.delete_voice(voice_id)
        except Exception as error:
            logger.warning("Voice deletion failed for session %s: %s", session_id, type(error).__name__)
            return {"hadVoice": True, "voiceDeleted": False}
        session.voice_id = None
        return {"hadVoice": True, "voiceDeleted": True}
