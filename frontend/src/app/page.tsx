"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  useLiveTranscription,
  type CoachingArea,
  type TranscriptionStatus,
} from "@/hooks/useLiveTranscription";
import { useReflectionDictation } from "@/hooks/useReflectionDictation";

const API_BASE = "http://localhost:8001";

const COACHING_AREAS: { value: CoachingArea; label: string }[] = [
  { value: "pace_and_pauses", label: "Pace & pauses" },
  { value: "turn_taking_and_interruptions", label: "Turn-taking & interruptions" },
  { value: "open_questions", label: "Open questions" },
  { value: "acknowledging_emotional_cues", label: "Acknowledging emotional cues" },
  { value: "stay_before_solving", label: "Stay with the customer before solving" },
];

type Phase =
  | "idle"
  | "starting"
  | "listening"
  | "finalizing"
  | "preparing_report"
  | "report"
  | "report_error"
  | "reflection";

type PostMeetingReport = {
  strengths: string[];
  improvements: string[];
  focus_summary: string;
  takeaway: string;
};

type ReflectionMessage = { author: "coach" | "advisor"; text: string };
type HistoryState = "empty" | "ready" | "unavailable";

const initialReflection: ReflectionMessage = {
  author: "coach",
  text: "How do you think the meeting went?",
};

const DEFAULT_FOCUS_AREAS: CoachingArea[] = [
  "acknowledging_emotional_cues",
  "stay_before_solving",
];

export default function Home() {
  const [focusAreas, setFocusAreas] = useState<CoachingArea[]>(DEFAULT_FOCUS_AREAS);
  const [focusHydrated, setFocusHydrated] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [report, setReport] = useState<PostMeetingReport | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [reflectionMessages, setReflectionMessages] = useState<ReflectionMessage[]>([
    initialReflection,
  ]);
  const [reflectionDraft, setReflectionDraft] = useState("");
  const [reflectionError, setReflectionError] = useState<string | null>(null);
  const [reflectionComplete, setReflectionComplete] = useState(false);
  const [reflectionPending, setReflectionPending] = useState(false);
  const [finishPending, setFinishPending] = useState(false);
  const [learningWarning, setLearningWarning] = useState<string | null>(null);
  const [recentInsight, setRecentInsight] = useState<string | null>(null);
  const [historyState, setHistoryState] = useState<HistoryState>("unavailable");
  const [focusSaveError, setFocusSaveError] = useState<string | null>(null);
  const pendingReflectionRef = useRef<{ id: string; message: string } | null>(null);
  const reflectionPendingRef = useRef(false);
  const finishPendingRef = useRef(false);
  const requestControllerRef = useRef<AbortController | null>(null);
  const homeLoadControllerRef = useRef<AbortController | null>(null);
  const homeLoadGenerationRef = useRef(0);
  const focusChangeGenerationRef = useRef(0);
  const focusSaveQueueRef = useRef<{ areas: CoachingArea[]; generation: number } | null>(null);
  const focusSaveProcessingRef = useRef(false);
  const focusHydratedRef = useRef(false);
  const activeSessionIdRef = useRef<string | null>(null);

  const {
    status,
    turns,
    completedSessionId,
    error: transcriptionError,
    currentNudge,
    start,
    stop,
    clearCompletedSession,
    isActive,
  } = useLiveTranscription();
  const appendReflectionText = useCallback((text: string) => {
    setReflectionDraft((current) => current.trim() ? `${current.trim()} ${text}` : text);
  }, []);
  const reflectionDictation = useReflectionDictation(appendReflectionText);

  useEffect(() => {
    activeSessionIdRef.current = completedSessionId;
  }, [completedSessionId]);

  const loadHomeLearning = useCallback(async () => {
    const generation = ++homeLoadGenerationRef.current;
    const focusGeneration = focusChangeGenerationRef.current;
    homeLoadControllerRef.current?.abort();
    const controller = new AbortController();
    homeLoadControllerRef.current = controller;
    try {
      const response = await fetch(`${API_BASE}/adviser-learning/home`, { signal: controller.signal });
      if (!response.ok) throw new Error("Learning unavailable");
      const payload = (await response.json()) as {
        focusAreas?: unknown;
        recentInsight?: unknown;
        historyState?: unknown;
      };
      const savedFocus = Array.isArray(payload.focusAreas)
        ? payload.focusAreas.filter(isCoachingArea)
        : [];
      if (generation !== homeLoadGenerationRef.current) return;
      if (focusChangeGenerationRef.current === focusGeneration) {
        if (savedFocus.length) {
          setFocusAreas(savedFocus);
        } else if (!focusHydratedRef.current) {
          setFocusAreas(DEFAULT_FOCUS_AREAS);
        }
      }
      setRecentInsight(typeof payload.recentInsight === "string" ? payload.recentInsight : null);
      setHistoryState(
        payload.historyState === "empty" || payload.historyState === "ready"
          ? payload.historyState
          : "unavailable",
      );
      if (focusChangeGenerationRef.current === focusGeneration) {
        setFocusSaveError(null);
      }
    } catch {
      if (generation !== homeLoadGenerationRef.current) return;
      setHistoryState("unavailable");
      if (!focusHydratedRef.current && focusChangeGenerationRef.current === focusGeneration) {
        setFocusAreas(DEFAULT_FOCUS_AREAS);
      }
    } finally {
      if (generation === homeLoadGenerationRef.current) {
        focusHydratedRef.current = true;
        setFocusHydrated(true);
        homeLoadControllerRef.current = null;
      }
    }
  }, []);

  const persistFocus = useCallback(() => {
    if (focusSaveProcessingRef.current) return;
    focusSaveProcessingRef.current = true;
    void (async () => {
      try {
        while (focusSaveQueueRef.current) {
          const pending = focusSaveQueueRef.current;
          focusSaveQueueRef.current = null;
          try {
            const response = await fetch(`${API_BASE}/adviser-learning/focus`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ focusAreas: pending.areas }),
            });
            if (!response.ok) throw new Error("Focus could not be saved.");
            if (pending.generation === focusChangeGenerationRef.current) {
              setFocusSaveError(null);
            }
          } catch {
            if (pending.generation === focusChangeGenerationRef.current) {
              setFocusSaveError("This focus will still be used for the meeting, but could not be saved.");
            }
          }
        }
      } finally {
        focusSaveProcessingRef.current = false;
      }
    })();
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadHomeLearning(), 0);
    return () => window.clearTimeout(timer);
  }, [loadHomeLearning]);

  const requestReport = useCallback(async (sessionId: string) => {
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 20_000);
    setPhase("preparing_report");
    setReportError(null);
    try {
      const response = await fetch(`${API_BASE}/post-meeting/${sessionId}/report`, {
        method: "POST",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const payload = (await response.json()) as { report?: PostMeetingReport };
      if (!payload.report) throw new Error("Feedback was not returned.");
      if (controller.signal.aborted || activeSessionIdRef.current !== sessionId) return;
      setReport(payload.report);
      setPhase("report");
    } catch (error) {
      if (requestControllerRef.current !== controller) return;
      if (controller.signal.aborted && error instanceof DOMException && error.name === "AbortError") {
        setReportError("Feedback took too long to prepare. Please retry.");
      } else {
        setReportError(error instanceof Error ? error.message : "Feedback could not be prepared.");
      }
      setPhase("report_error");
    } finally {
      window.clearTimeout(timeout);
      if (requestControllerRef.current === controller) requestControllerRef.current = null;
    }
  }, []);

  useEffect(() => {
    const timers: number[] = [];
    if (status === "stopped" && completedSessionId && !report && phase !== "report_error" && phase !== "preparing_report") {
      timers.push(window.setTimeout(() => void requestReport(completedSessionId), 0));
    }
    if (status === "stopped" && !completedSessionId && phase === "finalizing") {
      timers.push(window.setTimeout(() => setPhase("idle"), 0));
    }
    if (status === "error" && (phase === "starting" || phase === "listening" || phase === "finalizing")) {
      const message = transcriptionError ?? "The meeting could not continue. Please try again.";
      timers.push(
        window.setTimeout(() => {
          clearCompletedSession();
          setReport(null);
          setReportError(message);
          setReflectionMessages([initialReflection]);
          setReflectionDraft("");
          setReflectionError(null);
          setReflectionComplete(false);
          setReflectionPending(false);
          reflectionPendingRef.current = false;
          pendingReflectionRef.current = null;
          setPhase("idle");
        }, 0),
      );
    }
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [clearCompletedSession, completedSessionId, phase, report, requestReport, status, transcriptionError]);

  const toggleFocus = (area: CoachingArea) => {
    if (!focusHydrated || isActive || phase !== "idle") return;
    const next = focusAreas.includes(area)
      ? focusAreas.filter((item) => item !== area)
      : [...focusAreas, area];
    if (!next.length) return;
    const generation = ++focusChangeGenerationRef.current;
    setFocusAreas(next);
    setFocusSaveError(null);
    focusSaveQueueRef.current = { areas: next, generation };
    persistFocus();
  };

  const beginMeeting = () => {
    if (!focusHydrated) return;
    setReport(null);
    setReportError(null);
    setReflectionError(null);
    setReflectionComplete(false);
    setReflectionPending(false);
    reflectionPendingRef.current = false;
    setLearningWarning(null);
    setPhase("starting");
    void start(focusAreas);
  };

  const endMeeting = () => {
    setPhase("finalizing");
    stop();
  };

  const abandonMeeting = () => {
    reflectionDictation.cancel();
    activeSessionIdRef.current = null;
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;
    clearCompletedSession();
    setReport(null);
    setReportError(null);
    setReflectionMessages([initialReflection]);
    setReflectionDraft("");
    setReflectionError(null);
    setReflectionComplete(false);
    setReflectionPending(false);
    reflectionPendingRef.current = false;
    pendingReflectionRef.current = null;
    setFinishPending(false);
    finishPendingRef.current = false;
    setPhase("idle");
  };

  const finish = async () => {
    if (finishPendingRef.current) return;
    finishPendingRef.current = true;
    reflectionDictation.cancel();
    const sessionId = completedSessionId;
    activeSessionIdRef.current = null;
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;
    setFinishPending(true);
    setReflectionPending(false);
    let learningSaved = true;
    if (sessionId) {
      const completionController = new AbortController();
      const completionTimeout = window.setTimeout(() => completionController.abort(), 5_000);
      try {
        const completion = await fetch(`${API_BASE}/post-meeting/${sessionId}/complete`, {
          method: "POST",
          signal: completionController.signal,
        });
        if (!completion.ok) throw new Error("Learning completion failed.");
        const payload = (await completion.json()) as { learningSaved?: boolean };
        learningSaved = payload.learningSaved === true;
      } catch {
        learningSaved = false;
        const deleteController = new AbortController();
        const deleteTimeout = window.setTimeout(() => deleteController.abort(), 5_000);
        try {
          await fetch(`${API_BASE}/post-meeting/${sessionId}`, {
            method: "DELETE",
            signal: deleteController.signal,
          });
        } catch {
          // Frontend privacy cleanup must not depend on backend availability.
        } finally {
          window.clearTimeout(deleteTimeout);
        }
      } finally {
        window.clearTimeout(completionTimeout);
      }
    }
    clearCompletedSession();
    setReport(null);
    setReportError(null);
    setReflectionMessages([initialReflection]);
    setReflectionDraft("");
    setReflectionError(null);
    setReflectionComplete(false);
    setReflectionPending(false);
    reflectionPendingRef.current = false;
    pendingReflectionRef.current = null;
    setFinishPending(false);
    finishPendingRef.current = false;
    setLearningWarning(
      learningSaved
        ? null
        : "This meeting was cleared, but its coaching insight may not have been saved.",
    );
    setPhase("idle");
    void loadHomeLearning();
  };

  const openReflection = () => {
    reflectionDictation.cancel();
    setReflectionMessages([initialReflection]);
    setReflectionDraft("");
    setReflectionError(null);
    setReflectionComplete(false);
    setReflectionPending(false);
    reflectionPendingRef.current = false;
    pendingReflectionRef.current = null;
    setPhase("reflection");
  };

  const sendReflection = async () => {
    const message = reflectionDraft.trim();
    if (!message || !completedSessionId || reflectionComplete || reflectionPendingRef.current) return;
    reflectionPendingRef.current = true;
    const pending = pendingReflectionRef.current;
    const messageId = pending?.message === message ? pending.id : crypto.randomUUID();
    pendingReflectionRef.current = { id: messageId, message };
    setReflectionError(null);
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    setReflectionPending(true);
    try {
      const response = await fetch(
        `${API_BASE}/post-meeting/${completedSessionId}/reflection`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messageId, message }),
          signal: controller.signal,
        },
      );
      if (!response.ok) throw new Error(await readApiError(response));
      const payload = (await response.json()) as {
        coach_message?: string;
        complete?: boolean;
        takeaway?: string | null;
      };
      if (!payload.coach_message) throw new Error("Reflection did not return a response.");
      if (controller.signal.aborted || activeSessionIdRef.current !== completedSessionId) return;
      setReflectionMessages((current) => [
        ...current,
        { author: "advisor", text: message },
        { author: "coach", text: payload.coach_message as string },
      ]);
      setReflectionDraft("");
      pendingReflectionRef.current = null;
      if (payload.complete) setReflectionComplete(true);
      if (payload.takeaway) {
        setReflectionMessages((current) => [
          ...current,
          { author: "coach", text: `TAKEAWAY_FOR_NEXT_TIME:${payload.takeaway}` },
        ]);
      }
    } catch (error) {
      if (requestControllerRef.current !== controller) return;
      setReflectionError(
        controller.signal.aborted
          ? "Reflection took too long to respond. Please retry."
          : error instanceof Error
            ? error.message
            : "Reflection could not respond. Please try again.",
      );
    } finally {
      window.clearTimeout(timeout);
      if (requestControllerRef.current === controller) requestControllerRef.current = null;
      reflectionPendingRef.current = false;
      setReflectionPending(false);
    }
  };

  const isMeeting = (phase === "starting" || phase === "listening" || phase === "finalizing") && status !== "error";
  const effectiveError = transcriptionError && (isMeeting || status === "error")
    ? transcriptionError
    : phase === "idle"
      ? reportError
      : null;

  if (phase === "preparing_report" || phase === "finalizing") {
    return <TransitionScreen />;
  }
  if (phase === "report" && report) {
    return <ReportView report={report} finishing={finishPending} onReflect={openReflection} onFinish={() => void finish()} />;
  }
  if (phase === "report_error") {
    return <ReportErrorView message={reportError ?? "Feedback could not be prepared."} finishing={finishPending} onRetry={() => completedSessionId && void requestReport(completedSessionId)} onFinish={() => void finish()} />;
  }
  if (phase === "reflection" && report) {
    return <ReflectionView messages={reflectionMessages} draft={reflectionDraft} error={reflectionError} dictationStatus={reflectionDictation.status} dictationError={reflectionDictation.error} complete={reflectionComplete} sending={reflectionPending} finishing={finishPending} onDraftChange={setReflectionDraft} onSend={() => void sendReflection()} onStartDictation={() => void reflectionDictation.start()} onStopDictation={reflectionDictation.stop} onBack={() => { reflectionDictation.cancel(); setPhase("report"); }} onFinish={() => void finish()} />;
  }

  return (
    <main className="min-h-screen bg-[#f7f9ff] px-5 py-6 text-[#17234a] sm:px-8 lg:px-12">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-6xl flex-col">
        <header className="flex flex-wrap items-center justify-between gap-4"><Brand />{isMeeting && <div className="flex items-center gap-3"><button type="button" onClick={abandonMeeting} className="rounded-xl px-3 py-2 text-sm font-semibold text-[#65708d] transition hover:bg-white hover:text-[#34405f] focus:outline-none focus:ring-4 focus:ring-[#e5e3ff]">← Home</button><StatusBadge status={status} /></div>}</header>
        {isMeeting ? <MeetingView focusAreas={focusAreas} turns={turns} currentNudge={currentNudge} status={status} error={effectiveError} onEnd={endMeeting} /> : <HomeView focusAreas={focusAreas} focusHydrated={focusHydrated} error={effectiveError} recentInsight={recentInsight} historyState={historyState} focusSaveError={focusSaveError} learningWarning={learningWarning} onToggle={toggleFocus} onStart={beginMeeting} />}
      </div>
    </main>
  );
}

async function readApiError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: { message?: string } | string };
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail?.message) return payload.detail.message;
  } catch {
    // Use the stable fallback below.
  }
  return "The coaching service could not complete that step. Please try again.";
}

function Brand() {
  return <div className="flex items-center gap-3"><span className="grid h-11 w-11 place-items-center rounded-2xl bg-[#5146e5] text-xl font-bold text-white shadow-[0_8px_18px_rgba(81,70,229,.22)]">C</span><p className="text-lg font-bold tracking-tight">Compassion Coach</p></div>;
}

function HomeView({ focusAreas, focusHydrated, error, recentInsight, historyState, focusSaveError, learningWarning, onToggle, onStart }: { focusAreas: CoachingArea[]; focusHydrated: boolean; error: string | null; recentInsight: string | null; historyState: HistoryState; focusSaveError: string | null; learningWarning: string | null; onToggle: (area: CoachingArea) => void; onStart: () => void }) {
  const insight = focusHydrated
    ? recentInsight ?? (historyState === "empty" ? "Complete a meeting to create your first coaching insight." : "Recent coaching insight is unavailable right now.")
    : null;
  return <section className="grid flex-1 items-start gap-8 py-10 lg:grid-cols-[1.05fr_.95fr]"><div className="flex flex-col items-start lg:sticky lg:top-8"><h1 className="max-w-xl text-4xl font-bold tracking-[-.04em] sm:text-5xl">Stay present in the conversation.</h1><p className="mt-5 max-w-lg text-lg leading-8 text-[#5d6884]">Choose what you want to practise. Your coach listens quietly and steps in only when useful.</p><fieldset className="mt-7 max-w-xl" disabled={!focusHydrated} aria-busy={!focusHydrated}><legend className="text-sm font-bold text-[#34405f]">Coaching focus</legend><div className="mt-3 flex flex-wrap gap-2">{COACHING_AREAS.map((area) => { const selected = focusHydrated && focusAreas.includes(area.value); return <button key={area.value} type="button" aria-pressed={selected} onClick={() => onToggle(area.value)} className={`rounded-full border px-3.5 py-2 text-sm font-semibold transition disabled:cursor-wait disabled:opacity-50 ${selected ? "border-[#7770e8] bg-[#eceaff] text-[#332b9d]" : "border-[#dfe4f3] bg-white text-[#65708d] hover:border-[#b9b5f6]"}`}>{area.label}</button>; })}</div></fieldset><button type="button" onClick={onStart} disabled={!focusHydrated} className="mt-8 inline-flex min-h-13 items-center justify-center rounded-2xl bg-[#5146e5] px-6 text-base font-semibold text-white shadow-[0_10px_22px_rgba(81,70,229,.24)] transition hover:bg-[#4338ca] focus:outline-none focus:ring-4 focus:ring-[#c9c5ff] disabled:cursor-wait disabled:opacity-50">Start meeting</button>{(error || focusSaveError) && <div role="alert" className="mt-5 max-w-lg rounded-2xl border border-[#f4c5b6] bg-[#fff3ef] px-4 py-3 text-sm font-semibold leading-6 text-[#8b452f]">{error ?? focusSaveError}</div>}{learningWarning && <p role="status" className="mt-4 max-w-lg text-sm font-medium leading-6 text-[#7b5a36]">{learningWarning}</p>}<p className="mt-7 text-sm leading-6 text-[#707c98]">Conversation audio, transcript, and customer details are temporary.</p></div><section className="min-h-36 rounded-[1.5rem] border border-[#cedcff] bg-[#eaf1ff] p-5 shadow-[0_18px_45px_rgba(81,70,229,.08)]"><p className="text-sm font-bold text-[#344a80]">Recent coaching insight</p><p className="mt-2 min-h-14 text-base leading-7 text-[#435a83]">{insight}</p></section></section>;
}

function MeetingView({ focusAreas, turns, currentNudge, status, error, onEnd }: { focusAreas: CoachingArea[]; turns: ReturnType<typeof useLiveTranscription>["turns"]; currentNudge: ReturnType<typeof useLiveTranscription>["currentNudge"]; status: TranscriptionStatus; error: string | null; onEnd: () => void }) {
  return <section className="grid flex-1 items-start gap-8 py-10 lg:grid-cols-[.9fr_1.1fr]"><div className="flex flex-col items-start lg:sticky lg:top-8"><h1 className="max-w-xl text-4xl font-bold tracking-[-.04em] sm:text-5xl">Stay present in the conversation.</h1><div className="mt-7 max-w-xl"><p className="text-sm font-semibold text-[#687491]">Today’s focus</p><div className="mt-2 flex flex-wrap gap-2">{focusAreas.map((area) => <span key={area} className="rounded-full bg-[#eceaff] px-3 py-1.5 text-xs font-semibold text-[#5146a5]">{labelForArea(area)}</span>)}</div></div><button type="button" onClick={onEnd} disabled={status === "stopping"} className="mt-8 inline-flex min-h-13 items-center justify-center rounded-2xl bg-[#b85c6b] px-6 text-base font-semibold text-white shadow-[0_10px_22px_rgba(126,56,72,.18)] transition hover:bg-[#a94d5e] focus:outline-none focus:ring-4 focus:ring-[#efcbd2] disabled:cursor-wait disabled:opacity-65">{status === "stopping" ? "Finishing…" : "End meeting"}</button>{error && <div role="alert" className="mt-5 max-w-lg rounded-2xl border border-[#f4c5b6] bg-[#fff3ef] px-4 py-3 text-sm font-semibold leading-6 text-[#8b452f]">{error}</div>}</div><div className="space-y-5"><section className="min-h-44 rounded-[1.7rem] border border-[#d8d5ff] bg-gradient-to-br from-[#f0efff] via-[#f5f4ff] to-[#edf5ff] p-6 shadow-[0_18px_45px_rgba(81,70,229,.10)]" aria-live="polite"><p className="text-xs font-bold tracking-[.12em] text-[#5146e5]">LIVE COACH</p>{currentNudge ? <div className="mt-5 border-l-4 border-[#7770e8] pl-5"><p className="text-2xl font-bold leading-9 text-[#17234a]">{currentNudge.text}</p><p className="mt-2 text-sm font-semibold text-[#665fb8]">A small moment to try now</p></div> : <div className="mt-5"><p className="text-xl font-bold text-[#28345b]">Listening quietly…</p><p className="mt-2 leading-7 text-[#6b7591]">The coach stays silent unless there is a clear, useful prompt.</p></div>}</section><details open className="overflow-hidden rounded-[1.7rem] border border-[#dfe4f3] bg-white shadow-[0_16px_40px_rgba(48,59,113,.07)]"><summary className="cursor-pointer px-5 py-4 text-sm font-bold text-[#5146e5] sm:px-6">Conversation transcript · {turns.length} finalized turns</summary><div className="max-h-[24rem] overflow-y-auto border-t border-[#e7eaf4] p-5 sm:p-6" aria-live="polite">{turns.length === 0 ? <p className="py-10 text-center font-medium text-[#7a86a1]">Finalized conversation turns will appear here.</p> : <ol className="space-y-4">{turns.map((turn) => <li key={turn.id} className={`rounded-2xl border p-4 ${turn.speaker === "advisor" ? "border-[#d4d1ff] bg-[#f3f1ff]" : "border-[#cbeadf] bg-[#eefaf6]"}`}><div className="flex items-center justify-between gap-4"><p className={`text-xs font-bold uppercase tracking-[.1em] ${turn.speaker === "advisor" ? "text-[#5146e5]" : "text-[#138467]"}`}>{turn.speaker}</p><p className="text-xs font-semibold text-[#8a94ad]">{formatTimestamp(turn.startTimeMs)}</p></div><p className="mt-2 text-base font-medium leading-7 text-[#2f3a5d]">{turn.text}</p></li>)}</ol>}</div></details></div></section>;
}

function TransitionScreen() {
  return <main className="grid min-h-screen place-items-center bg-[#f7f9ff] px-6 text-center text-[#17234a]"><section className="max-w-md rounded-[1.7rem] border border-[#d8d5ff] bg-white p-8 shadow-[0_20px_55px_rgba(48,59,113,.09)]"><span className="mx-auto grid h-16 w-16 place-items-center rounded-full bg-[#eceaff] text-2xl text-[#5146e5]">⌁</span><h1 className="mt-6 text-2xl font-bold">Preparing your feedback…</h1><p className="mt-3 leading-7 text-[#687491]">This will only take a moment.</p></section></main>;
}

function ReportView({ report, finishing, onReflect, onFinish }: { report: PostMeetingReport; finishing: boolean; onReflect: () => void; onFinish: () => void }) {
  return <main className="min-h-screen bg-[#f7f9ff] px-5 py-6 text-[#17234a] sm:px-8 lg:px-12"><div className="mx-auto max-w-5xl"><header className="flex items-center justify-between"><Brand /><button type="button" disabled={finishing} onClick={onFinish} className="rounded-xl px-3 py-2 text-sm font-semibold text-[#65708d] transition hover:bg-white hover:text-[#34405f] focus:outline-none focus:ring-4 focus:ring-[#e5e3ff] disabled:cursor-not-allowed disabled:opacity-50">← Home</button></header><h1 className="mt-6 text-center text-3xl font-bold tracking-[-.035em] sm:text-4xl">A few things to carry forward.</h1><section className="mt-6 grid gap-4 md:grid-cols-2"><ReportCard title="What went well" items={report.strengths} tone="blue" /><ReportCard title="What to improve" items={report.improvements} tone="lavender" /></section><section className="mt-4 rounded-[1.4rem] border border-[#dfe4f3] bg-white px-5 py-4"><p className="text-sm font-bold text-[#5146e5]">Your focus</p><p className="mt-1.5 text-sm font-semibold leading-6 text-[#445070]">{report.focus_summary}</p></section><div className="mt-5 flex flex-col justify-center gap-3 sm:flex-row"><ActionButton disabled={finishing} onClick={onReflect}>Reflect <span className="ml-2">→</span></ActionButton><ActionButton variant="secondary" disabled={finishing} onClick={onFinish}>{finishing ? "Finishing…" : "Finish"}</ActionButton></div></div></main>;
}

function ReportCard({ title, items, tone }: { title: string; items: string[]; tone: "blue" | "lavender" }) {
  return <article className={`rounded-[1.5rem] border p-5 sm:p-6 ${tone === "blue" ? "border-[#cedcff] bg-[#eef3ff]" : "border-[#d8d3ff] bg-[#f3f0ff]"}`}><p className="text-sm font-bold tracking-wide text-[#4059b8]">{title}</p><ul className="mt-3 space-y-2 text-xl font-bold leading-8 text-[#27325e]">{items.map((item) => <li key={item}>{item}</li>)}</ul></article>;
}

function ReportErrorView({ message, finishing, onRetry, onFinish }: { message: string; finishing: boolean; onRetry: () => void; onFinish: () => void }) {
  return <main className="grid min-h-screen place-items-center bg-[#f7f9ff] px-6 text-[#17234a]"><section className="max-w-lg rounded-[1.7rem] border border-[#f0d2c8] bg-white p-8 text-center shadow-[0_20px_55px_rgba(48,59,113,.09)]"><h1 className="text-2xl font-bold">Feedback needs another try</h1><p className="mt-3 leading-7 text-[#687491]">{message}</p><div className="mt-7 flex justify-center gap-3"><ActionButton disabled={finishing} onClick={onRetry}>Retry</ActionButton><ActionButton variant="secondary" disabled={finishing} onClick={onFinish}>{finishing ? "Finishing…" : "Finish"}</ActionButton></div></section></main>;
}

function ReflectionView({ messages, draft, error, dictationStatus, dictationError, complete, sending, finishing, onDraftChange, onSend, onStartDictation, onStopDictation, onBack, onFinish }: { messages: ReflectionMessage[]; draft: string; error: string | null; dictationStatus: "idle" | "listening" | "processing" | "error"; dictationError: string | null; complete: boolean; sending: boolean; finishing: boolean; onDraftChange: (value: string) => void; onSend: () => void; onStartDictation: () => void; onStopDictation: () => void; onBack: () => void; onFinish: () => void }) {
  const takeaway = messages.find((message) => message.text.startsWith("TAKEAWAY_FOR_NEXT_TIME:"))?.text.replace("TAKEAWAY_FOR_NEXT_TIME:", "");
  const visibleMessages = messages.filter((message) => !message.text.startsWith("TAKEAWAY_FOR_NEXT_TIME:"));
  const dictationActive = dictationStatus === "listening" || dictationStatus === "processing";
  const dictationMessage = dictationStatus === "listening" ? "Listening…" : dictationStatus === "processing" ? "Transcribing…" : dictationError;
  return <main className="min-h-screen bg-[#f7f9ff] px-5 py-8 text-[#17234a] sm:px-8"><div className="mx-auto max-w-3xl"><header className="flex items-center justify-between gap-4"><Brand /><button type="button" disabled={finishing || dictationActive} onClick={onBack} className="rounded-xl px-3 py-2 text-sm font-semibold text-[#536080] hover:bg-white disabled:cursor-not-allowed disabled:opacity-50">← Back to report</button></header><section className="mt-8 overflow-hidden rounded-[1.7rem] bg-white shadow-[0_20px_55px_rgba(48,59,113,.09)]"><div className="border-b border-[#ebedf5] px-6 py-5"><p className="text-sm font-bold tracking-wide text-[#5146e5]">A SHORT REFLECTION</p><h1 className="mt-1 text-2xl font-bold tracking-[-.03em]">Make the learning your own.</h1><p className="mt-2 text-sm leading-6 text-[#687491]">Take a moment to notice what you want to carry into the next conversation.</p></div><div className="space-y-3 p-5 sm:p-6">{visibleMessages.map((message, index) => <div key={`${message.author}-${index}`} className={`flex ${message.author === "advisor" ? "justify-end" : "justify-start"}`}><div className={`max-w-[88%] rounded-[1.25rem] px-4 py-3 text-sm leading-6 sm:text-base ${message.author === "advisor" ? "rounded-br-md bg-[#5146e5] text-white" : "rounded-bl-md bg-[#eef0ff] text-[#29345f]"}`}>{message.author === "coach" && <p className="mb-1 text-xs font-bold tracking-wide text-[#5146e5]">YOUR COACH</p>}{message.text}</div></div>)}</div>{!complete && <div className="border-t border-[#ebedf5] bg-[#fbfcff] p-4"><form onSubmit={(event) => { event.preventDefault(); onSend(); }} className="flex gap-3"><label className="sr-only" htmlFor="reflection">Your reflection</label><div className="flex min-w-0 flex-1 gap-2"><input id="reflection" value={draft} disabled={sending || finishing || dictationActive} onChange={(event) => onDraftChange(event.target.value)} placeholder="Write your reflection…" className="min-h-12 min-w-0 flex-1 rounded-2xl border border-[#dce1ee] bg-white px-4 text-base outline-none placeholder:text-[#8a94ad] focus:border-[#5146e5] focus:ring-4 focus:ring-[#e5e3ff] disabled:opacity-60" /><button type="button" aria-label={dictationActive ? "Stop reflection dictation" : "Start reflection dictation"} title={dictationActive ? "Stop dictation" : "Dictate reflection"} disabled={sending || finishing || dictationStatus === "processing"} onClick={dictationActive ? onStopDictation : onStartDictation} className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl border text-lg transition focus:outline-none focus:ring-4 focus:ring-[#c9c5ff] disabled:cursor-not-allowed disabled:opacity-50 ${dictationStatus === "listening" ? "border-[#5146e5] bg-[#eceaff] text-[#5146e5]" : "border-[#dce1ee] bg-white text-[#536080] hover:border-[#8c83ff]"}`}><DictationIcon active={dictationStatus === "listening"} /></button></div><ActionButton type="submit" disabled={!draft.trim() || sending || finishing || dictationActive}>{sending ? "Sending…" : "Send"}</ActionButton></form>{dictationMessage && <p role={dictationError ? "alert" : "status"} className={`mt-3 text-sm font-semibold ${dictationError ? "text-[#9a4a32]" : "text-[#536080]"}`}>{dictationMessage}</p>}{error && <p role="alert" className="mt-3 text-sm font-semibold text-[#9a4a32]">{error}</p>}</div>}</section>{complete && takeaway && <section className="mt-4 rounded-[1.4rem] border border-[#cedcff] bg-[#eef3ff] p-5"><p className="text-xs font-bold tracking-[.12em] text-[#4059b8]">TAKEAWAY FOR NEXT TIME</p><p className="mt-1 text-base font-bold text-[#27325e]">{takeaway}</p></section>}<div className="mt-5 flex justify-end"><ActionButton variant="secondary" disabled={finishing || dictationActive} onClick={onFinish}>{finishing ? "Finishing…" : "Finish"}</ActionButton></div></div></main>;
}

function DictationIcon({ active }: { active: boolean }) {
  return active ? <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="6" y="6" width="12" height="12" rx="1" /></svg> : <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10a7 7 0 0 0 14 0M12 19v3M8 22h8" /></svg>;
}

function ActionButton({ children, onClick, variant = "primary", type = "button", disabled = false }: { children: React.ReactNode; onClick?: () => void; variant?: "primary" | "secondary"; type?: "button" | "submit"; disabled?: boolean }) {
  return <button type={type} disabled={disabled} onClick={onClick} className={`inline-flex min-h-12 items-center justify-center rounded-2xl px-5 text-base font-semibold transition focus:outline-none focus:ring-4 focus:ring-[#c9c5ff] disabled:cursor-not-allowed disabled:opacity-50 ${variant === "primary" ? "bg-[#5146e5] text-white shadow-[0_10px_22px_rgba(81,70,229,.24)] hover:bg-[#4338ca]" : "border border-[#d9def7] bg-white text-[#27325e] hover:bg-[#f4f5ff]"}`}>{children}</button>;
}

function StatusBadge({ status }: { status: TranscriptionStatus }) {
  const active = status === "listening";
  return <div className="flex items-center gap-2 rounded-full border border-[#e1e5f2] bg-white px-4 py-2.5 text-sm font-bold shadow-sm"><span className={`h-2.5 w-2.5 rounded-full ${active ? "animate-pulse bg-[#16a47e]" : "bg-[#a6afc3]"}`} />{active ? "Listening" : statusLabel(status)}</div>;
}

function statusLabel(status: TranscriptionStatus) {
  return { idle: "Ready", requesting: "Requesting microphone", connecting: "Connecting", listening: "Listening", stopping: "Finishing", stopped: "Stopped", error: "Needs attention" }[status];
}

function labelForArea(area: CoachingArea) {
  return COACHING_AREAS.find((item) => item.value === area)?.label ?? area;
}

function isCoachingArea(value: unknown): value is CoachingArea {
  return typeof value === "string" && COACHING_AREAS.some((area) => area.value === value);
}

function formatTimestamp(milliseconds: number) {
  const totalSeconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(totalSeconds / 60)).padStart(2, "0")}:${String(totalSeconds % 60).padStart(2, "0")}`;
}
