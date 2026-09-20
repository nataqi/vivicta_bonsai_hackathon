"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const AUDIO_MIME_TYPE = "audio/webm;codecs=opus";
const DICTATION_URL = "ws://localhost:8001/ws/reflection-dictation";

export type ReflectionDictationStatus = "idle" | "listening" | "processing" | "error";

type ServerMessage =
  | { type: "session.ready" }
  | { type: "transcript"; text: string }
  | { type: "error"; message: string };

export function useReflectionDictation(onTranscript: (text: string) => void) {
  const [status, setStatus] = useState<ReflectionDictationStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const onTranscriptRef = useRef(onTranscript);
  const websocketRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sendChainRef = useRef<Promise<void>>(Promise.resolve());
  const generationRef = useRef(0);
  const mountedRef = useRef(true);
  const expectedCloseRef = useRef(false);
  const stopRequestedRef = useRef(false);

  useEffect(() => {
    onTranscriptRef.current = onTranscript;
  }, [onTranscript]);

  const dispose = useCallback(() => {
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
      websocket &&
      (websocket.readyState === WebSocket.OPEN || websocket.readyState === WebSocket.CONNECTING)
    ) {
      websocket.close();
    }
    websocketRef.current = null;
    sendChainRef.current = Promise.resolve();
  }, []);

  const fail = useCallback((message: string, generation: number) => {
    if (!mountedRef.current || generation !== generationRef.current) return;
    expectedCloseRef.current = true;
    dispose();
    setError(message);
    setStatus("error");
  }, [dispose]);

  const start = useCallback(async () => {
    if (status === "listening" || status === "processing") return;
    expectedCloseRef.current = true;
    dispose();
    expectedCloseRef.current = false;
    stopRequestedRef.current = false;
    const generation = ++generationRef.current;
    setError(null);

    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser does not support microphone recording.");
      setStatus("error");
      return;
    }
    if (!MediaRecorder.isTypeSupported(AUDIO_MIME_TYPE)) {
      setError("Use a current Chrome or Edge browser for reflection dictation.");
      setStatus("error");
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (microphoneError) {
      const denied = microphoneError instanceof DOMException &&
        (microphoneError.name === "NotAllowedError" || microphoneError.name === "PermissionDeniedError");
      setError(denied ? "Microphone access was denied. Allow access and try again." : "The microphone could not be started. Try again.");
      setStatus("error");
      return;
    }
    if (generation !== generationRef.current || !mountedRef.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    streamRef.current = stream;
    const websocket = new WebSocket(DICTATION_URL);
    websocketRef.current = websocket;

    websocket.onmessage = (event) => {
      if (generation !== generationRef.current) return;
      let message: ServerMessage;
      try {
        message = JSON.parse(event.data) as ServerMessage;
      } catch {
        fail("The transcription service returned an unreadable response.", generation);
        return;
      }
      if (message.type === "session.ready") {
        if (stopRequestedRef.current) {
          if (websocket.readyState === WebSocket.OPEN) websocket.send(JSON.stringify({ type: "stop" }));
          return;
        }
        const recorder = new MediaRecorder(stream, { mimeType: AUDIO_MIME_TYPE });
        recorderRef.current = recorder;
        recorder.ondataavailable = (audioEvent) => {
          if (!audioEvent.data.size) return;
          sendChainRef.current = sendChainRef.current.then(async () => {
            const audio = await audioEvent.data.arrayBuffer();
            if (generation === generationRef.current && websocket.readyState === WebSocket.OPEN) websocket.send(audio);
          }).catch(() => fail("Microphone audio could not be sent. Please try again.", generation));
        };
        recorder.onerror = () => fail("Microphone recording stopped unexpectedly. Please try again.", generation);
        recorder.start(250);
        setStatus("listening");
        return;
      }
      if (message.type === "transcript") {
        expectedCloseRef.current = true;
        dispose();
        if (message.text.trim()) onTranscriptRef.current(message.text.trim());
        setStatus("idle");
        return;
      }
      if (message.type === "error") fail(message.message || "Reflection dictation failed. Please try again.", generation);
    };
    websocket.onerror = () => {
      if (!expectedCloseRef.current) fail("Could not connect to reflection dictation. Please try again.", generation);
    };
    websocket.onclose = () => {
      if (generation === generationRef.current && mountedRef.current && !expectedCloseRef.current) {
        fail("Reflection dictation disconnected. Please try again.", generation);
      }
    };
  }, [dispose, fail, status]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    const websocket = websocketRef.current;
    if (!recorder && !websocket) return;
    stopRequestedRef.current = true;
    setStatus("processing");
    const sendStop = async () => {
      await sendChainRef.current;
      if (websocketRef.current !== websocket) return;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (websocket?.readyState === WebSocket.OPEN) websocket.send(JSON.stringify({ type: "stop" }));
      else fail("Reflection dictation disconnected. Please try again.", generationRef.current);
    };
    if (recorder?.state === "recording") {
      recorder.onstop = () => void sendStop();
      recorder.stop();
    } else {
      void sendStop();
    }
  }, [fail]);

  const cancel = useCallback(() => {
    generationRef.current += 1;
    expectedCloseRef.current = true;
    stopRequestedRef.current = false;
    dispose();
    setError(null);
    setStatus("idle");
  }, [dispose]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      expectedCloseRef.current = true;
      dispose();
    };
  }, [dispose]);

  return { status, error, start, stop, cancel };
}
