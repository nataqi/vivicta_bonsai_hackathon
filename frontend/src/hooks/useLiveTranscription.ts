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

export function useLiveTranscription() {
  const [status, setStatus] = useState<TranscriptionStatus>("idle");
  const [turns, setTurns] = useState<SpeakerTurn[]>([]);
  const [error, setError] = useState<string | null>(null);

  const websocketRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sendChainRef = useRef<Promise<void>>(Promise.resolve());
  const generationRef = useRef(0);
  const mountedRef = useRef(true);
  const expectedCloseRef = useRef(false);
  const stopRequestedRef = useRef(false);

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
  }, []);

  const start = useCallback(async () => {
    expectedCloseRef.current = true;
    disposeSession();
    expectedCloseRef.current = false;
    stopRequestedRef.current = false;
    const generation = ++generationRef.current;

    setTurns([]);
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
        setTurns((current) => [...current, message.turn]);
        return;
      }

      if (message.type === "session.stopped") {
        expectedCloseRef.current = true;
        disposeSession();
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
  }, [disposeSession]);

  const stop = useCallback(() => {
    stopRequestedRef.current = true;
    setStatus("stopping");

    const recorder = recorderRef.current;
    const websocket = websocketRef.current;

    const sendStop = async () => {
      await sendChainRef.current;
      if (websocketRef.current !== websocket) return;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (websocket?.readyState === WebSocket.OPEN) {
        websocket.send(JSON.stringify({ type: "stop" }));
      } else {
        expectedCloseRef.current = true;
        disposeSession();
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
      expectedCloseRef.current = true;
      disposeSession();
      setStatus("stopped");
    } else {
      expectedCloseRef.current = true;
      disposeSession();
      setStatus("stopped");
    }
  }, [disposeSession]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      expectedCloseRef.current = true;
      disposeSession();
    };
  }, [disposeSession]);

  return {
    status,
    turns,
    error,
    start,
    stop,
    isActive:
      status === "requesting" ||
      status === "connecting" ||
      status === "listening" ||
      status === "stopping",
  };
}
