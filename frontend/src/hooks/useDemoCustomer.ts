"use client";

import { useEffect, useRef, useState } from "react";
import anna from "@/lib/demo/anna.json";
import type { DemoAudio, TranscriptionStatus } from "@/hooks/useLiveTranscription";

export type DemoPhase = "off" | "waiting" | "speaking" | "your_turn" | "finishing";

// Mic RMS (0-1) above which the adviser counts as speaking. Tune for the room if needed.
const SPEECH_LEVEL = 0.02;
const POLL_MS = 100;
const QUIET_AFTER_SPEECH_MS = 1_500;
const ECHO_TAIL_MS = 400;
const ANSWER_CAP_MS = 15_000;
const CLOSING_WINDOW_MS = 8_000;
const MAX_ANSWER_MS = 60_000;
const BEAT_MS = 1_000;

const abortError = () => new DOMException("Demo stopped", "AbortError");

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError());
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(abortError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function abortable<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError());
    signal.addEventListener("abort", () => reject(abortError()), { once: true });
    promise.then(resolve, reject);
  });
}

async function waitFor(condition: () => boolean, timeoutMs: number, signal: AbortSignal): Promise<boolean> {
  const deadline = performance.now() + timeoutMs;
  while (performance.now() < deadline) {
    if (condition()) return true;
    await sleep(POLL_MS, signal);
  }
  return false;
}

/**
 * Waits for the adviser to start speaking (up to capMs), then until they have been quiet for a
 * moment. If they never start, it simply returns once capMs has passed.
 */
async function listenForAnswer(audio: DemoAudio, capMs: number, signal: AbortSignal): Promise<void> {
  const started = await waitFor(() => audio.getMicLevel() > SPEECH_LEVEL, capMs, signal);
  if (!started) return;
  let lastSpeech = performance.now();
  await waitFor(
    () => {
      const now = performance.now();
      if (audio.getMicLevel() > SPEECH_LEVEL) lastSpeech = now;
      return now - lastSpeech >= QUIET_AFTER_SPEECH_MS;
    },
    MAX_ANSWER_MS,
    signal,
  );
}

/**
 * Plays the scripted fictional customer. She never speaks first (the backend labels the first
 * voice as the adviser), then speaks a line, waits for the adviser's answer, and continues. After
 * her closing line and a short reply window it calls onFinished so the meeting ends by itself.
 */
export function useDemoCustomer({
  enabled,
  status,
  audio,
  onFinished,
}: {
  enabled: boolean;
  status: TranscriptionStatus;
  audio: DemoAudio;
  onFinished: () => void;
}) {
  const [phase, setPhase] = useState<Exclude<DemoPhase, "off">>("waiting");
  const [error, setError] = useState<string | null>(null);
  const onFinishedRef = useRef(onFinished);

  useEffect(() => {
    onFinishedRef.current = onFinished;
  }, [onFinished]);

  const running = enabled && status === "listening";

  useEffect(() => {
    if (!running) return;
    const controller = new AbortController();
    const { signal } = controller;

    const run = async () => {
      try {
        setError(null);
        setPhase("waiting");
        // Decode while the adviser says hello, so the first line is ready when needed.
        const clips = Promise.all(anna.lines.map((line) => audio.decode(line.file)));
        clips.catch(() => undefined);
        await listenForAnswer(audio, Infinity, signal);
        const buffers = await abortable(clips, signal);

        for (let index = 0; index < buffers.length; index += 1) {
          const last = index === buffers.length - 1;
          setPhase("speaking");
          await abortable(audio.play(buffers[index]), signal);
          await sleep(ECHO_TAIL_MS, signal);
          setPhase("your_turn");
          await listenForAnswer(audio, last ? CLOSING_WINDOW_MS : ANSWER_CAP_MS, signal);
          if (!last) await sleep(BEAT_MS, signal);
        }
        setPhase("finishing");
        onFinishedRef.current();
      } catch (failure) {
        if (signal.aborted) return;
        setError(failure instanceof Error ? failure.message : "The demo customer could not continue.");
      }
    };
    void run();

    return () => controller.abort();
  }, [audio, running]);

  return { phase: running ? phase : ("off" as DemoPhase), error, customerName: anna.name };
}
