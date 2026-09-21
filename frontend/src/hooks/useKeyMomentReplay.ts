"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { buildAdviserSample, decodeRecording, sliceClip } from "@/lib/audioClips";
import type { CoachingArea, SpeakerTurn } from "@/hooks/useLiveTranscription";

const API_BASE = "http://localhost:8001";
const BETTER_TAKE_TIMEOUT_MS = 45_000;

export type KeyMoment = {
  turn_id: string;
  area: CoachingArea;
  kind: "improvement" | "strength";
  customer_context: string;
  better_answer: string;
  why: string;
  start_time_ms: number;
  end_time_ms: number;
};

export type Track = "original" | "better";
export type ClipStatus = "idle" | "loading" | "ready" | "error";
export type VoiceMode = "cloned" | "neutral";

/**
 * Plays the adviser's own key moment and an AI "better take" for it. Audio lives only in this
 * hook (decoded buffer and object URLs) and is released by reset().
 */
export function useKeyMomentReplay(getRecording: () => Blob | null) {
  const [playing, setPlaying] = useState<Track | null>(null);
  const [originalStatus, setOriginalStatus] = useState<ClipStatus>("idle");
  const [betterStatus, setBetterStatus] = useState<ClipStatus>("idle");
  const [voiceMode, setVoiceMode] = useState<VoiceMode | null>(null);
  const [error, setError] = useState<string | null>(null);

  const bufferRef = useRef<Promise<AudioBuffer> | null>(null);
  const urlsRef = useRef<Partial<Record<Track, string>>>({});
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const generationRef = useRef(0);

  const stop = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.onended = null;
      audio.pause();
    }
    audioRef.current = null;
    setPlaying(null);
  }, []);

  const reset = useCallback(() => {
    generationRef.current += 1;
    stop();
    Object.values(urlsRef.current).forEach((url) => url && URL.revokeObjectURL(url));
    urlsRef.current = {};
    bufferRef.current = null;
    setOriginalStatus("idle");
    setBetterStatus("idle");
    setVoiceMode(null);
    setError(null);
  }, [stop]);

  useEffect(() => reset, [reset]);

  const play = useCallback(
    async (track: Track, url: string) => {
      stop();
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        if (audioRef.current === audio) {
          audioRef.current = null;
          setPlaying(null);
        }
      };
      setPlaying(track);
      try {
        await audio.play();
      } catch {
        if (audioRef.current === audio) {
          audioRef.current = null;
          setPlaying(null);
        }
        setError("Audio could not be played in this browser.");
      }
    },
    [stop],
  );

  const ensureBuffer = useCallback(() => {
    if (!bufferRef.current) {
      const recording = getRecording();
      if (!recording) throw new Error("The meeting audio is no longer available.");
      bufferRef.current = decodeRecording(recording);
    }
    return bufferRef.current;
  }, [getRecording]);

  const playOriginal = useCallback(
    async (moment: KeyMoment) => {
      setError(null);
      const cached = urlsRef.current.original;
      if (cached) {
        await play("original", cached);
        return;
      }
      const generation = generationRef.current;
      setOriginalStatus("loading");
      try {
        const buffer = await ensureBuffer();
        if (generation !== generationRef.current) return;
        const url = URL.createObjectURL(sliceClip(buffer, moment.start_time_ms, moment.end_time_ms));
        urlsRef.current.original = url;
        setOriginalStatus("ready");
        await play("original", url);
      } catch (failure) {
        if (generation !== generationRef.current) return;
        bufferRef.current = null;
        setOriginalStatus("error");
        setError(failure instanceof Error ? failure.message : "This moment could not be replayed.");
      }
    },
    [ensureBuffer, play],
  );

  const playBetter = useCallback(
    async (sessionId: string, turns: SpeakerTurn[]) => {
      setError(null);
      const cached = urlsRef.current.better;
      if (cached) {
        await play("better", cached);
        return;
      }
      const generation = generationRef.current;
      setBetterStatus("loading");
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), BETTER_TAKE_TIMEOUT_MS);
      try {
        const buffer = await ensureBuffer();
        // Too little adviser speech means no sample is sent, and a neutral voice is used instead.
        const sample = buildAdviserSample(buffer, turns);
        const response = await fetch(`${API_BASE}/post-meeting/${sessionId}/voice/better-take`, {
          method: "POST",
          headers: { "Content-Type": "audio/wav" },
          body: sample ?? new Blob([]),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(await readError(response));
        const audio = await response.blob();
        if (generation !== generationRef.current) return;
        const url = URL.createObjectURL(audio);
        urlsRef.current.better = url;
        setVoiceMode(response.headers.get("X-Voice-Mode") === "cloned" ? "cloned" : "neutral");
        setBetterStatus("ready");
        await play("better", url);
      } catch (failure) {
        if (generation !== generationRef.current) return;
        setBetterStatus("error");
        setError(
          controller.signal.aborted
            ? "The better take took too long. Please try again."
            : failure instanceof Error
              ? failure.message
              : "The better take could not be prepared.",
        );
      } finally {
        window.clearTimeout(timeout);
      }
    },
    [ensureBuffer, play],
  );

  return { playing, originalStatus, betterStatus, voiceMode, error, playOriginal, playBetter, stop, reset };
}

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: { message?: string } | string };
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail?.message) return payload.detail.message;
  } catch {
    // Use the stable fallback below.
  }
  return "The better take could not be prepared. Please try again.";
}
