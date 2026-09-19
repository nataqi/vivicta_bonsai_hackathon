"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const AUDIO_MIME_TYPE = "audio/webm;codecs=opus";
const TRANSCRIPTION_URL = "ws://localhost:8001/ws/transcription";

export type SpeakerTurn = {
  id: string;
  speaker: "advisor" | "customer";
  text: string;
  startTimeMs: number;
  endTimeMs: number;
  durationMs: number;
  isFinal: boolean;
};

export type CoachingArea =
  | "pace_and_pauses"
  | "turn_taking_and_interruptions"
  | "open_questions"
  | "acknowledging_emotional_cues"
  | "stay_before_solving";

export type LiveNudge = {
  area: CoachingArea;
  nudgeKey: string;
  text: string;
  timestampMs: number;
};

export type TranscriptionStatus =
  | "idle"
  | "requesting"
  | "connecting"
  | "listening"
  | "stopping"
  | "stopped"
  | "error";

type ServerMessage =
  | { type: "session.ready" }
  | { type: "session.stopped" }
  | { type: "speaker_turn"; turn: SpeakerTurn }
  | { type: "live_nudge"; nudge: LiveNudge }
  | { type: "error"; message: string };

function isSpeakerTurn(value: unknown): value is SpeakerTurn {
  if (!value || typeof value !== "object") return false;
  const turn = value as Partial<SpeakerTurn>;
  return (
    typeof turn.id === "string" &&
    (turn.speaker === "advisor" || turn.speaker === "customer") &&
    typeof turn.text === "string" &&
    typeof turn.startTimeMs === "number" &&
    typeof turn.endTimeMs === "number" &&
    typeof turn.durationMs === "number" &&
    turn.isFinal === true
  );
}

function isLiveNudge(value: unknown): value is LiveNudge {
  if (!value || typeof value !== "object") return false;
  const nudge = value as Partial<LiveNudge>;
  return (
    typeof nudge.area === "string" &&
    typeof nudge.nudgeKey === "string" &&
    typeof nudge.text === "string" &&
    typeof nudge.timestampMs === "number"
  );
}

export function useLiveTranscription() {
  const [status, setStatus] = useState<TranscriptionStatus>("idle");
  const [turns, setTurns] = useState<SpeakerTurn[]>([]);
  const [sessionTurns, setSessionTurns] = useState<SpeakerTurn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [currentNudge, setCurrentNudge] = useState<LiveNudge | null>(null);

  const websocketRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sendChainRef = useRef<Promise<void>>(Promise.resolve());
  const generationRef = useRef(0);
  const mountedRef = useRef(true);
  const expectedCloseRef = useRef(false);
  const stopRequestedRef = useRef(false);
  const acceptVisibleLiveContentRef = useRef(false);
  const acceptSessionTurnsRef = useRef(false);
  const nudgeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearLiveContent = useCallback(() => {
    setTurns([]);
    setCurrentNudge(null);
    if (nudgeTimerRef.current) clearTimeout(nudgeTimerRef.current);
    nudgeTimerRef.current = null;
  }, []);

  const disposeSession = useCallback((closeSocket = true) => {
    const recorder = recorderRef.current;
    if (recorder) {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.onerror = null;
      if (recorder.state !== "inactive") recorder.stop();
    }
    recorderRef.current = null;

    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;

    const websocket = websocketRef.current;
    if (
      closeSocket &&
      websocket &&
      (websocket.readyState === WebSocket.OPEN ||
        websocket.readyState === WebSocket.CONNECTING)
    ) {
      websocket.close();
    }
    websocketRef.current = null;
    sendChainRef.current = Promise.resolve();
    if (nudgeTimerRef.current) clearTimeout(nudgeTimerRef.current);
    nudgeTimerRef.current = null;
  }, []);

  const start = useCallback(async (focusAreas: CoachingArea[]) => {
    expectedCloseRef.current = true;
    disposeSession();
    expectedCloseRef.current = false;
    stopRequestedRef.current = false;
    acceptVisibleLiveContentRef.current = true;
    acceptSessionTurnsRef.current = true;
    const generation = ++generationRef.current;

    clearLiveContent();
    setSessionTurns([]);
    setError(null);
    setStatus("requesting");

    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser does not support microphone recording.");
      setStatus("error");
      return;
    }

    if (!MediaRecorder.isTypeSupported(AUDIO_MIME_TYPE)) {
      setError("Use a current Chrome or Edge browser for live transcription.");
      setStatus("error");
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (microphoneError) {
      if (generation !== generationRef.current || !mountedRef.current) return;
      const permissionDenied =
        microphoneError instanceof DOMException &&
        (microphoneError.name === "NotAllowedError" ||
          microphoneError.name === "PermissionDeniedError");
      setError(
        permissionDenied
          ? "Microphone access was denied. Allow access in your browser and try again."
          : "The microphone could not be started. Check that it is available and try again.",
      );
      setStatus("error");
      return;
    }

    if (generation !== generationRef.current || !mountedRef.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }

    streamRef.current = stream;
    setStatus("connecting");

    const websocket = new WebSocket(TRANSCRIPTION_URL);
    websocketRef.current = websocket;

    const fail = (message: string) => {
      if (generation !== generationRef.current || !mountedRef.current) return;
      expectedCloseRef.current = true;
      acceptVisibleLiveContentRef.current = false;
      acceptSessionTurnsRef.current = false;
      disposeSession();
      setError(message);
      setStatus("error");
    };

    websocket.onmessage = (event) => {
      if (generation !== generationRef.current) return;

      let message: ServerMessage;
      try {
        message = JSON.parse(event.data) as ServerMessage;
      } catch {
        fail("The transcription service returned an unreadable response.");
        return;
      }

      if (message.type === "session.ready") {
        if (stopRequestedRef.current) {
          websocket.send(JSON.stringify({ type: "stop" }));
          return;
        }
        if (recorderRef.current) return;

        websocket.send(JSON.stringify({ type: "session.configure", focusAreas }));

        const recorder = new MediaRecorder(stream, { mimeType: AUDIO_MIME_TYPE });
        recorderRef.current = recorder;
        recorder.ondataavailable = (audioEvent) => {
          if (!audioEvent.data.size) return;
          sendChainRef.current = sendChainRef.current
            .then(async () => {
              const audio = await audioEvent.data.arrayBuffer();
              if (
                generation === generationRef.current &&
                websocket.readyState === WebSocket.OPEN
              ) {
                websocket.send(audio);
              }
            })
            .catch(() => {
              fail("Microphone audio could not be sent. Please try again.");
            });
        };
        recorder.onerror = () => {
          fail("Microphone recording stopped unexpectedly. Please try again.");
        };
        recorder.start(250);
        setStatus("listening");
        return;
      }

      if (message.type === "speaker_turn" && isSpeakerTurn(message.turn)) {
        if (!acceptSessionTurnsRef.current) return;
        setSessionTurns((current) => [...current, message.turn]);
        if (acceptVisibleLiveContentRef.current) {
          setTurns((current) => [...current, message.turn]);
        }
        return;
      }

      if (message.type === "live_nudge" && isLiveNudge(message.nudge)) {
        if (!acceptVisibleLiveContentRef.current) return;
        if (nudgeTimerRef.current) clearTimeout(nudgeTimerRef.current);
        setCurrentNudge(message.nudge);
        nudgeTimerRef.current = setTimeout(() => {
          if (
            generation === generationRef.current &&
            mountedRef.current &&
            acceptVisibleLiveContentRef.current
          ) {
            setCurrentNudge(null);
          }
        }, 8_000);
        return;
      }

      if (message.type === "session.stopped") {
        expectedCloseRef.current = true;
        acceptSessionTurnsRef.current = false;
        disposeSession();
        clearLiveContent();
        setStatus("stopped");
        return;
      }

      if (message.type === "error") {
        fail(message.message || "Live transcription stopped unexpectedly.");
      }
    };

    websocket.onerror = () => {
      if (!expectedCloseRef.current) {
        fail("Could not connect to live transcription. Check that the backend is running.");
      }
    };

    websocket.onclose = () => {
      if (
        generation === generationRef.current &&
        mountedRef.current &&
        !expectedCloseRef.current
      ) {
        fail("The live transcription connection closed. Please try again.");
      }
    };
  }, [clearLiveContent, disposeSession]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    const websocket = websocketRef.current;

    if (!streamRef.current && !websocket && !recorder) {
      generationRef.current += 1;
      stopRequestedRef.current = true;
      acceptVisibleLiveContentRef.current = false;
      acceptSessionTurnsRef.current = false;
      clearLiveContent();
      setStatus("stopped");
      return;
    }

    stopRequestedRef.current = true;
    acceptVisibleLiveContentRef.current = false;
    clearLiveContent();
    setStatus("stopping");

    const sendStop = async () => {
      await sendChainRef.current;
      if (websocketRef.current !== websocket) return;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (websocket?.readyState === WebSocket.OPEN) {
        websocket.send(JSON.stringify({ type: "stop" }));
      } else {
        expectedCloseRef.current = true;
        disposeSession();
        clearLiveContent();
        if (mountedRef.current) setStatus("stopped");
      }
    };

    if (recorder?.state === "recording") {
      recorder.onstop = () => {
        void sendStop();
      };
      recorder.stop();
    } else if (websocket?.readyState === WebSocket.OPEN) {
      void sendStop();
    } else if (websocket?.readyState === WebSocket.CONNECTING) {
      generationRef.current += 1;
      expectedCloseRef.current = true;
      acceptSessionTurnsRef.current = false;
      disposeSession();
      clearLiveContent();
      setStatus("stopped");
    } else {
      expectedCloseRef.current = true;
      acceptSessionTurnsRef.current = false;
      disposeSession();
      clearLiveContent();
      setStatus("stopped");
    }
  }, [clearLiveContent, disposeSession]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      acceptVisibleLiveContentRef.current = false;
      acceptSessionTurnsRef.current = false;
      generationRef.current += 1;
      expectedCloseRef.current = true;
      disposeSession();
    };
  }, [disposeSession]);

  return {
    status,
    turns,
    sessionTurns,
    error,
    currentNudge,
    start,
    stop,
    isActive:
      status === "requesting" ||
      status === "connecting" ||
      status === "listening" ||
      status === "stopping",
  };
}
