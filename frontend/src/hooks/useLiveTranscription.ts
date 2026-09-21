"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const AUDIO_MIME_TYPE = "audio/webm;codecs=opus";
const TRANSCRIPTION_URL = "ws://localhost:8001/ws/transcription";
const FINALIZATION_TIMEOUT_MS = 10_000;

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

/**
 * Demo-only audio hooks. In demo mode the mic and the scripted customer are mixed into the
 * recorded stream, so transcription hears the customer cleanly on speakers or headphones.
 */
export type DemoAudio = {
  decode: (url: string) => Promise<AudioBuffer>;
  play: (buffer: AudioBuffer) => Promise<void>;
  getMicLevel: () => number;
};

export type StartOptions = { demo?: boolean };

export type TranscriptionStatus =
  | "idle"
  | "requesting"
  | "connecting"
  | "listening"
  | "stopping"
  | "stopped"
  | "error";

type ServerMessage =
  | { type: "session.ready"; sessionId: string }
  | { type: "session.stopped"; sessionId: string }
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
  const [completedSessionId, setCompletedSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [currentNudge, setCurrentNudge] = useState<LiveNudge | null>(null);

  const websocketRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sendChainRef = useRef<Promise<void>>(Promise.resolve());
  // Temporary, in-browser only: kept so the adviser can replay a key moment after the meeting.
  const recordingChunksRef = useRef<Blob[]>([]);
  const generationRef = useRef(0);
  const mountedRef = useRef(true);
  const expectedCloseRef = useRef(false);
  const stopRequestedRef = useRef(false);
  const acceptVisibleLiveContentRef = useRef(false);
  const acceptSessionTurnsRef = useRef(false);
  const nudgeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const finalizationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const demoDestinationRef = useRef<MediaStreamAudioDestinationNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const levelBufferRef = useRef<Float32Array<ArrayBuffer> | null>(null);

  const clearLiveContent = useCallback(() => {
    setTurns([]);
    setCurrentNudge(null);
    if (nudgeTimerRef.current) clearTimeout(nudgeTimerRef.current);
    nudgeTimerRef.current = null;
    if (finalizationTimerRef.current) clearTimeout(finalizationTimerRef.current);
    finalizationTimerRef.current = null;
  }, []);

  const closeAudioGraph = useCallback(() => {
    const context = audioContextRef.current;
    audioContextRef.current = null;
    demoDestinationRef.current = null;
    analyserRef.current = null;
    if (context && context.state !== "closed") void context.close();
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
    closeAudioGraph();
  }, [closeAudioGraph]);

  const start = useCallback(async (focusAreas: CoachingArea[], options?: StartOptions) => {
    expectedCloseRef.current = true;
    disposeSession();
    expectedCloseRef.current = false;
    // Created before any await so it stays inside the button click's user activation.
    if (options?.demo) audioContextRef.current = new AudioContext();
    stopRequestedRef.current = false;
    acceptVisibleLiveContentRef.current = true;
    acceptSessionTurnsRef.current = true;
    recordingChunksRef.current = [];
    const generation = ++generationRef.current;

    clearLiveContent();
    setSessionTurns([]);
    setCompletedSessionId(null);
    setError(null);
    setStatus("requesting");

    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      closeAudioGraph();
      setError("This browser does not support microphone recording.");
      setStatus("error");
      return;
    }

    if (!MediaRecorder.isTypeSupported(AUDIO_MIME_TYPE)) {
      closeAudioGraph();
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
      closeAudioGraph();
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

    // Demo only: mix the mic with the scripted customer, and record that mix.
    let recordingStream = stream;
    const demoContext = audioContextRef.current;
    if (demoContext) {
      const micSource = demoContext.createMediaStreamSource(stream);
      const destination = demoContext.createMediaStreamDestination();
      const analyser = demoContext.createAnalyser();
      analyser.fftSize = 1024;
      micSource.connect(destination);
      micSource.connect(analyser);
      demoDestinationRef.current = destination;
      analyserRef.current = analyser;
      recordingStream = destination.stream;
      void demoContext.resume();
    }
    setStatus("connecting");

    const websocket = new WebSocket(TRANSCRIPTION_URL);
    websocketRef.current = websocket;

    const fail = (message: string) => {
      if (generation !== generationRef.current || !mountedRef.current) return;
      expectedCloseRef.current = true;
      acceptVisibleLiveContentRef.current = false;
      acceptSessionTurnsRef.current = false;
      recordingChunksRef.current = [];
      disposeSession();
      clearLiveContent();
      setSessionTurns([]);
      setCompletedSessionId(null);
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

        const recorder = new MediaRecorder(recordingStream, { mimeType: AUDIO_MIME_TYPE });
        recorderRef.current = recorder;
        recorder.ondataavailable = (audioEvent) => {
          if (!audioEvent.data.size) return;
          if (generation === generationRef.current) recordingChunksRef.current.push(audioEvent.data);
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
        if (typeof message.sessionId !== "string" || !message.sessionId) {
          fail("The completed meeting did not return a session identifier.");
          return;
        }
        expectedCloseRef.current = true;
        acceptSessionTurnsRef.current = false;
        disposeSession();
        clearLiveContent();
        setCompletedSessionId(message.sessionId);
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
  }, [clearLiveContent, closeAudioGraph, disposeSession]);

  const clearCompletedSession = useCallback(() => {
    generationRef.current += 1;
    expectedCloseRef.current = true;
    stopRequestedRef.current = false;
    acceptVisibleLiveContentRef.current = false;
    acceptSessionTurnsRef.current = false;
    recordingChunksRef.current = [];
    disposeSession();
    setSessionTurns([]);
    setCompletedSessionId(null);
    setError(null);
    clearLiveContent();
    setStatus("idle");
  }, [clearLiveContent, disposeSession]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    const websocket = websocketRef.current;
    const generation = generationRef.current;

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

    const armFinalizationTimeout = () => {
      if (finalizationTimerRef.current) clearTimeout(finalizationTimerRef.current);
      finalizationTimerRef.current = setTimeout(() => {
        if (!mountedRef.current || generation !== generationRef.current) return;
        generationRef.current += 1;
        expectedCloseRef.current = true;
        acceptSessionTurnsRef.current = false;
        recordingChunksRef.current = [];
        disposeSession();
        clearLiveContent();
        setSessionTurns([]);
        setCompletedSessionId(null);
        setError("The meeting took too long to finalize. Return home and start a new meeting.");
        setStatus("error");
      }, FINALIZATION_TIMEOUT_MS);
    };

    const sendStop = async () => {
      await sendChainRef.current;
      if (websocketRef.current !== websocket) return;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (websocket?.readyState === WebSocket.OPEN) {
        websocket.send(JSON.stringify({ type: "stop" }));
        armFinalizationTimeout();
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
      recordingChunksRef.current = [];
      disposeSession();
    };
  }, [disposeSession]);

  const getRecording = useCallback(() => {
    const chunks = recordingChunksRef.current;
    return chunks.length ? new Blob(chunks, { type: AUDIO_MIME_TYPE }) : null;
  }, []);

  const demoAudio = useMemo<DemoAudio>(
    () => ({
      decode: async (url) => {
        const context = audioContextRef.current;
        if (!context) throw new Error("Demo audio is not ready.");
        const response = await fetch(url);
        if (!response.ok) throw new Error("A demo audio clip could not be loaded.");
        return context.decodeAudioData(await response.arrayBuffer());
      },
      play: async (buffer) => {
        const context = audioContextRef.current;
        const destination = demoDestinationRef.current;
        if (!context || !destination) throw new Error("Demo audio is not ready.");
        await context.resume();
        await new Promise<void>((resolve) => {
          const source = context.createBufferSource();
          source.buffer = buffer;
          source.connect(destination); // the recording Deepgram transcribes
          source.connect(context.destination); // the room
          source.onended = () => resolve();
          source.start();
        });
      },
      getMicLevel: () => {
        const analyser = analyserRef.current;
        if (!analyser) return 0;
        if (!levelBufferRef.current || levelBufferRef.current.length !== analyser.fftSize) {
          levelBufferRef.current = new Float32Array(analyser.fftSize);
        }
        const samples = levelBufferRef.current;
        analyser.getFloatTimeDomainData(samples);
        let sum = 0;
        for (const sample of samples) sum += sample * sample;
        return Math.sqrt(sum / samples.length);
      },
    }),
    [],
  );

  return {
    status,
    turns,
    sessionTurns,
    completedSessionId,
    error,
    currentNudge,
    getRecording,
    demoAudio,
    start,
    stop,
    clearCompletedSession,
    isActive:
      status === "requesting" ||
      status === "connecting" ||
      status === "listening" ||
      status === "stopping",
  };
}
