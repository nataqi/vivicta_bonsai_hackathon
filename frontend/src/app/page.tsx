"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  useLiveTranscription,
  type CoachingArea,
  type TranscriptionStatus,
} from "@/hooks/useLiveTranscription";

const API_BASE = "http://localhost:8001";

const COACHING_AREAS: { value: CoachingArea; label: string }[] = [
  { value: "pace_and_pauses", label: "Pace & pauses" },
  { value: "turn_taking_and_interruptions", label: "Turn-taking" },
  { value: "open_questions", label: "Open questions" },
  { value: "acknowledging_emotional_cues", label: "Acknowledge emotion" },
  { value: "stay_before_solving", label: "Stay before solving" },
];

type Phase =
  | "idle"
  | "starting"
  | "listening"
  | "finalizing"
  | "preparing_report"
  | "report"
  | "report_error"
  | "reflection"
  | "finishing";

type PostMeetingReport = {
  strengths: string[];
  improvements: string[];
  focus_summary: string;
  takeaway: string;
};

type ReflectionMessage = { author: "coach" | "advisor"; text: string };

const initialReflection: ReflectionMessage = {
  author: "coach",
  text: "How do you think the meeting went?",
};

export default function Home() {
  const [focusAreas, setFocusAreas] = useState<CoachingArea[]>([
    "acknowledging_emotional_cues",
    "stay_before_solving",
  ]);
  const [phase, setPhase] = useState<Phase>("idle");
  const [report, setReport] = useState<PostMeetingReport | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [reflectionMessages, setReflectionMessages] = useState<ReflectionMessage[]>([
    initialReflection,
  ]);
  const [reflectionDraft, setReflectionDraft] = useState("");
  const [reflectionError, setReflectionError] = useState<string | null>(null);
  const [reflectionComplete, setReflectionComplete] = useState(false);
  const pendingReflectionRef = useRef<{ id: string; message: string } | null>(null);
  const requestControllerRef = useRef<AbortController | null>(null);
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

  useEffect(() => {
    activeSessionIdRef.current = completedSessionId;
  }, [completedSessionId]);

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
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [completedSessionId, phase, report, requestReport, status]);

  const toggleFocus = (area: CoachingArea) => {
    if (isActive || phase !== "idle") return;
    setFocusAreas((current) =>
      current.includes(area)
        ? current.filter((item) => item !== area)
        : [...current, area],
    );
  };

  const beginMeeting = () => {
    setReport(null);
    setReportError(null);
    setReflectionError(null);
    setReflectionComplete(false);
    setPhase("starting");
    void start(focusAreas);
  };

  const endMeeting = () => {
    setPhase("finalizing");
    stop();
  };

  const finish = async () => {
    const sessionId = completedSessionId;
    activeSessionIdRef.current = null;
    requestControllerRef.current?.abort();
    setPhase("finishing");
    if (sessionId) {
      const cleanupController = new AbortController();
      const cleanupTimeout = window.setTimeout(() => cleanupController.abort(), 3_000);
      try {
        await fetch(`${API_BASE}/post-meeting/${sessionId}`, { method: "DELETE", signal: cleanupController.signal });
      } catch {
        // Frontend privacy cleanup must not depend on backend availability.
      } finally {
        window.clearTimeout(cleanupTimeout);
      }
    }
    clearCompletedSession();
    setReport(null);
    setReportError(null);
    setReflectionMessages([initialReflection]);
    setReflectionDraft("");
    setReflectionError(null);
    setReflectionComplete(false);
    pendingReflectionRef.current = null;
    setPhase("idle");
  };

  const openReflection = () => {
    setReflectionMessages([initialReflection]);
    setReflectionDraft("");
    setReflectionError(null);
    setReflectionComplete(false);
    pendingReflectionRef.current = null;
    setPhase("reflection");
  };

  const sendReflection = async () => {
    const message = reflectionDraft.trim();
    if (!message || !completedSessionId || reflectionComplete) return;
    const pending = pendingReflectionRef.current;
    const messageId = pending?.message === message ? pending.id : crypto.randomUUID();
    pendingReflectionRef.current = { id: messageId, message };
    setReflectionError(null);
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
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
    }
  };

  const isMeeting = (phase === "starting" || phase === "listening" || phase === "finalizing") && status !== "error";
  const effectiveError = transcriptionError && (isMeeting || status === "error") ? transcriptionError : null;

  if (phase === "preparing_report" || phase === "finalizing") {
    return <TransitionScreen finalizing={phase === "finalizing"} />;
  }
  if (phase === "report" && report) {
    return <ReportView report={report} onReflect={openReflection} onFinish={() => void finish()} />;
  }
  if (phase === "report_error") {
    return <ReportErrorView message={reportError ?? "Feedback could not be prepared."} onRetry={() => completedSessionId && void requestReport(completedSessionId)} onFinish={() => void finish()} />;
  }
  if (phase === "reflection" && report) {
    return <ReflectionView messages={reflectionMessages} draft={reflectionDraft} error={reflectionError} complete={reflectionComplete} onDraftChange={setReflectionDraft} onSend={() => void sendReflection()} onBack={() => setPhase("report")} onFinish={() => void finish()} />;
  }
  if (phase === "finishing") return <TransitionScreen finalizing={false} finishing />;

  return (
    <main className="min-h-screen bg-[#f7f9ff] px-5 py-6 text-[#17234a] sm:px-8 lg:px-12">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-6xl flex-col">
        <header className="flex flex-wrap items-center justify-between gap-4"><Brand /><StatusBadge status={status} /></header>
        {isMeeting ? <MeetingView focusAreas={focusAreas} turns={turns} currentNudge={currentNudge} status={status} error={effectiveError} onEnd={endMeeting} /> : <HomeView focusAreas={focusAreas} error={effectiveError} onToggle={toggleFocus} onStart={beginMeeting} />}
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
  return <div className="flex items-center gap-3"><span className="grid h-11 w-11 place-items-center rounded-2xl bg-[#5146e5] text-xl font-bold text-white shadow-[0_8px_18px_rgba(81,70,229,.22)]">C</span><div><p className="text-lg font-bold tracking-tight">Compassion Coach</p><p className="text-sm font-medium text-[#687491]">Live meeting coach</p></div></div>;
}

function HomeView({ focusAreas, error, onToggle, onStart }: { focusAreas: CoachingArea[]; error: string | null; onToggle: (area: CoachingArea) => void; onStart: () => void }) {
  return <section className="grid flex-1 items-start gap-8 py-10 lg:grid-cols-[.9fr_1.1fr]"><div className="flex flex-col items-start lg:sticky lg:top-8"><p className="text-sm font-bold tracking-[.12em] text-[#5146e5]">LIVE COACHING</p><h1 className="mt-3 max-w-xl text-4xl font-bold tracking-[-.04em] sm:text-5xl">Stay present in the conversation.</h1><p className="mt-5 max-w-lg text-lg leading-8 text-[#5d6884]">Choose what you want to practise. The coach listens quietly and steps in only when useful.</p><fieldset className="mt-7 max-w-xl"><legend className="text-sm font-bold text-[#34405f]">Coaching focus</legend><div className="mt-3 flex flex-wrap gap-2">{COACHING_AREAS.map((area) => { const selected = focusAreas.includes(area.value); return <button key={area.value} type="button" aria-pressed={selected} onClick={() => onToggle(area.value)} className={`rounded-full border px-3.5 py-2 text-sm font-semibold transition ${selected ? "border-[#7770e8] bg-[#eceaff] text-[#332b9d]" : "border-[#dfe4f3] bg-white text-[#65708d] hover:border-[#b9b5f6]"}`}>{area.label}</button>; })}</div></fieldset><div className="mt-8 flex flex-wrap items-center gap-3"><button type="button" onClick={onStart} className="inline-flex min-h-13 items-center justify-center rounded-2xl bg-[#5146e5] px-6 text-base font-semibold text-white shadow-[0_10px_22px_rgba(81,70,229,.24)] transition hover:bg-[#4338ca] focus:outline-none focus:ring-4 focus:ring-[#c9c5ff]">Start meeting</button><p className="text-sm font-medium text-[#707c98]">Ready when you are.</p></div>{error && <div role="alert" className="mt-5 max-w-lg rounded-2xl border border-[#f4c5b6] bg-[#fff3ef] px-4 py-3 text-sm font-semibold leading-6 text-[#8b452f]">{error}</div>}<div className="mt-8 flex w-full max-w-lg items-center gap-4 rounded-2xl border border-[#dfe4f3] bg-white px-4 py-3 shadow-sm"><span className="grid h-12 w-12 place-items-center rounded-full bg-[#eef0f7] text-xl text-[#75819e]" aria-hidden="true">◉</span><div><p className="font-bold text-[#34405f]">Microphone inactive</p><p className="mt-0.5 text-sm text-[#707c98]">Audio, transcript, and coaching context are temporary.</p></div></div></div><section className="rounded-[1.7rem] border border-[#cedcff] bg-[#eaf1ff] p-6 shadow-[0_18px_45px_rgba(81,70,229,.08)] sm:p-7"><p className="text-sm font-bold tracking-[.1em] text-[#3557b7]">YOUR PRIVATE COACH</p><p className="mt-3 text-xl font-bold leading-8 text-[#1e315e]">The session stays focused on how you communicate, so you can make one useful adjustment at a time.</p><div className="mt-5 border-t border-[#cad8f5] pt-4"><p className="text-sm font-bold text-[#344a80]">Choose a focus</p><p className="mt-1 text-base leading-7 text-[#435a83]">Your selections guide live prompts and the short report after the conversation.</p></div></section></section>;
}

function MeetingView({ focusAreas, turns, currentNudge, status, error, onEnd }: { focusAreas: CoachingArea[]; turns: ReturnType<typeof useLiveTranscription>["turns"]; currentNudge: ReturnType<typeof useLiveTranscription>["currentNudge"]; status: TranscriptionStatus; error: string | null; onEnd: () => void }) {
  return <section className="grid flex-1 items-start gap-8 py-10 lg:grid-cols-[.9fr_1.1fr]"><div className="flex flex-col items-start lg:sticky lg:top-8"><p className="text-sm font-bold tracking-[.12em] text-[#5146e5]">LIVE COACHING</p><h1 className="mt-3 max-w-xl text-4xl font-bold tracking-[-.04em] sm:text-5xl">Stay present in the conversation.</h1><p className="mt-5 max-w-lg text-lg leading-8 text-[#5d6884]">The coach is listening quietly and will step in only when a useful prompt is clear.</p><div className="mt-7 rounded-2xl border border-[#dfe4f3] bg-white px-4 py-3 text-sm font-semibold text-[#596785]">Today’s focus: {focusAreas.length ? focusAreas.map(labelForArea).join(" · ") : "All dimensions"}</div><button type="button" onClick={onEnd} disabled={status === "stopping"} className="mt-8 inline-flex min-h-13 items-center justify-center rounded-2xl bg-[#f17856] px-6 text-base font-semibold text-white shadow-[0_10px_22px_rgba(241,120,86,.22)] transition hover:bg-[#df6242] focus:outline-none focus:ring-4 focus:ring-[#ffd4c8] disabled:cursor-wait disabled:opacity-65">{status === "stopping" ? "Finishing…" : "End meeting"}</button>{error && <div role="alert" className="mt-5 max-w-lg rounded-2xl border border-[#f4c5b6] bg-[#fff3ef] px-4 py-3 text-sm font-semibold leading-6 text-[#8b452f]">{error}</div>}</div><div className="space-y-5"><section className="min-h-44 rounded-[1.7rem] border border-[#d8d5ff] bg-gradient-to-br from-[#f0efff] via-[#f5f4ff] to-[#edf5ff] p-6 shadow-[0_18px_45px_rgba(81,70,229,.10)]" aria-live="polite"><p className="text-xs font-bold tracking-[.12em] text-[#5146e5]">LIVE COACH</p>{currentNudge ? <div className="mt-5 border-l-4 border-[#7770e8] pl-5"><p className="text-2xl font-bold leading-9 text-[#17234a]">{currentNudge.text}</p><p className="mt-2 text-sm font-semibold text-[#665fb8]">A small moment to try now</p></div> : <div className="mt-5"><p className="text-xl font-bold text-[#28345b]">Listening quietly…</p><p className="mt-2 leading-7 text-[#6b7591]">The coach stays silent unless there is a clear, useful prompt.</p></div>}</section><details className="overflow-hidden rounded-[1.7rem] border border-[#dfe4f3] bg-white shadow-[0_16px_40px_rgba(48,59,113,.07)]"><summary className="cursor-pointer px-5 py-4 text-sm font-bold text-[#5146e5] sm:px-6">Debug transcript · {turns.length} finalized turns</summary><div className="max-h-[30rem] overflow-y-auto border-t border-[#e7eaf4] p-5 sm:p-6" aria-live="polite">{turns.length === 0 ? <p className="py-12 text-center font-medium text-[#7a86a1]">No finalized turns yet.</p> : <ol className="space-y-4">{turns.map((turn) => <li key={turn.id} className={`rounded-2xl border p-4 ${turn.speaker === "advisor" ? "border-[#d4d1ff] bg-[#f3f1ff]" : "border-[#cbeadf] bg-[#eefaf6]"}`}><div className="flex items-center justify-between gap-4"><p className={`text-xs font-bold uppercase tracking-[.1em] ${turn.speaker === "advisor" ? "text-[#5146e5]" : "text-[#138467]"}`}>{turn.speaker}</p><p className="text-xs font-semibold text-[#8a94ad]">{formatTimestamp(turn.startTimeMs)}</p></div><p className="mt-2 text-base font-medium leading-7 text-[#2f3a5d]">{turn.text}</p></li>)}</ol>}</div></details></div></section>;
}

function TransitionScreen({ finalizing, finishing = false }: { finalizing: boolean; finishing?: boolean }) {
  return <main className="grid min-h-screen place-items-center bg-[#f7f9ff] px-6 text-center text-[#17234a]"><section className="max-w-md rounded-[1.7rem] border border-[#d8d5ff] bg-white p-8 shadow-[0_20px_55px_rgba(48,59,113,.09)]"><span className="mx-auto grid h-16 w-16 place-items-center rounded-full bg-[#eceaff] text-2xl text-[#5146e5]">⌁</span><h1 className="mt-6 text-2xl font-bold">{finishing ? "Closing this session…" : finalizing ? "Finalizing the last words…" : "Preparing your feedback…"}</h1><p className="mt-3 leading-7 text-[#687491]">{finishing ? "Clearing the temporary meeting context." : finalizing ? "The live view has closed while we finish the transcript." : "Your coach is reviewing the conversation."}</p></section></main>;
}

function ReportView({ report, onReflect, onFinish }: { report: PostMeetingReport; onReflect: () => void; onFinish: () => void }) {
  return <main className="min-h-screen bg-[#f7f9ff] px-5 py-8 text-[#17234a] sm:px-8 lg:px-12"><div className="mx-auto max-w-5xl"><header className="flex items-center justify-between"><Brand /><span className="text-sm font-semibold text-[#687491]">Your coaching report</span></header><h1 className="mt-10 text-center text-3xl font-bold tracking-[-.035em] sm:text-4xl">A few things to carry forward.</h1><section className="mt-8 grid gap-4 md:grid-cols-2"><ReportCard title="WHAT WENT WELL" items={report.strengths} tone="blue" /><ReportCard title="TRY NEXT TIME" items={report.improvements} tone="lavender" /></section><section className="mt-4 grid gap-4 rounded-[1.4rem] border border-[#dfe4f3] bg-white p-5 sm:grid-cols-[1fr_1.15fr] sm:items-center"><div className="sm:pr-6"><p className="text-xs font-bold tracking-[.12em] text-[#5146e5]">YOUR FOCUS</p><p className="mt-1.5 text-sm font-semibold leading-6 text-[#445070]">{report.focus_summary}</p></div><div className="border-t border-[#e7eaf4] pt-4 sm:border-l sm:border-t-0 sm:py-1 sm:pl-6"><p className="text-xs font-bold tracking-[.12em] text-[#5146e5]">TAKEAWAY</p><p className="mt-1.5 text-sm font-semibold leading-6 text-[#445070]">{report.takeaway}</p></div></section><div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row"><ActionButton onClick={onReflect}>Reflect <span className="ml-2">→</span></ActionButton><ActionButton variant="secondary" onClick={onFinish}>Finish</ActionButton></div></div></main>;
}

function ReportCard({ title, items, tone }: { title: string; items: string[]; tone: "blue" | "lavender" }) {
  return <article className={`rounded-[1.5rem] border p-5 sm:p-6 ${tone === "blue" ? "border-[#cedcff] bg-[#eef3ff]" : "border-[#d8d3ff] bg-[#f3f0ff]"}`}><p className="text-sm font-bold tracking-wide text-[#4059b8]">{title}</p><ul className="mt-3 space-y-2 text-xl font-bold leading-8 text-[#27325e]">{items.map((item) => <li key={item}>{item}</li>)}</ul></article>;
}

function ReportErrorView({ message, onRetry, onFinish }: { message: string; onRetry: () => void; onFinish: () => void }) {
  return <main className="grid min-h-screen place-items-center bg-[#f7f9ff] px-6 text-[#17234a]"><section className="max-w-lg rounded-[1.7rem] border border-[#f0d2c8] bg-white p-8 text-center shadow-[0_20px_55px_rgba(48,59,113,.09)]"><h1 className="text-2xl font-bold">Feedback needs another try</h1><p className="mt-3 leading-7 text-[#687491]">{message}</p><div className="mt-7 flex justify-center gap-3"><ActionButton onClick={onRetry}>Retry</ActionButton><ActionButton variant="secondary" onClick={onFinish}>Finish</ActionButton></div></section></main>;
}

function ReflectionView({ messages, draft, error, complete, onDraftChange, onSend, onBack, onFinish }: { messages: ReflectionMessage[]; draft: string; error: string | null; complete: boolean; onDraftChange: (value: string) => void; onSend: () => void; onBack: () => void; onFinish: () => void }) {
  const takeaway = messages.find((message) => message.text.startsWith("TAKEAWAY_FOR_NEXT_TIME:"))?.text.replace("TAKEAWAY_FOR_NEXT_TIME:", "");
  const visibleMessages = messages.filter((message) => !message.text.startsWith("TAKEAWAY_FOR_NEXT_TIME:"));
  return <main className="min-h-screen bg-[#f7f9ff] px-5 py-8 text-[#17234a] sm:px-8"><div className="mx-auto max-w-3xl"><header className="flex items-center justify-between"><Brand /><button type="button" onClick={onBack} className="rounded-xl px-3 py-2 text-sm font-semibold text-[#536080] hover:bg-white">← Report</button></header><section className="mt-8 overflow-hidden rounded-[1.7rem] bg-white shadow-[0_20px_55px_rgba(48,59,113,.09)]"><div className="border-b border-[#ebedf5] px-6 py-5"><p className="text-sm font-bold tracking-wide text-[#5146e5]">A SHORT REFLECTION</p><h1 className="mt-1 text-2xl font-bold tracking-[-.03em]">Make the learning your own.</h1></div><div className="space-y-3 p-5 sm:p-6">{visibleMessages.map((message, index) => <div key={`${message.author}-${index}`} className={`flex ${message.author === "advisor" ? "justify-end" : "justify-start"}`}><div className={`max-w-[88%] rounded-[1.25rem] px-4 py-3 text-sm leading-6 sm:text-base ${message.author === "advisor" ? "rounded-br-md bg-[#5146e5] text-white" : "rounded-bl-md bg-[#eef0ff] text-[#29345f]"}`}>{message.author === "coach" && <p className="mb-1 text-xs font-bold tracking-wide text-[#5146e5]">YOUR COACH</p>}{message.text}</div></div>)}</div>{!complete && <div className="border-t border-[#ebedf5] bg-[#fbfcff] p-4"><form onSubmit={(event) => { event.preventDefault(); onSend(); }} className="flex gap-3"><label className="sr-only" htmlFor="reflection">Your reflection</label><input id="reflection" value={draft} onChange={(event) => onDraftChange(event.target.value)} placeholder="Write your reflection…" className="min-h-12 flex-1 rounded-2xl border border-[#dce1ee] bg-white px-4 text-base outline-none placeholder:text-[#8a94ad] focus:border-[#5146e5] focus:ring-4 focus:ring-[#e5e3ff]" /><ActionButton type="submit" disabled={!draft.trim()}>Send</ActionButton></form>{error && <p role="alert" className="mt-3 text-sm font-semibold text-[#9a4a32]">{error}</p>}</div>}</section>{complete && takeaway && <section className="mt-4 flex flex-col items-start justify-between gap-4 rounded-[1.4rem] border border-[#cedcff] bg-[#eef3ff] p-5 sm:flex-row sm:items-center"><div><p className="text-xs font-bold tracking-[.12em] text-[#4059b8]">TAKEAWAY FOR NEXT TIME</p><p className="mt-1 text-base font-bold text-[#27325e]">{takeaway}</p></div><ActionButton variant="secondary" onClick={onFinish}>Finish</ActionButton></section>}{error && <div className="mt-4 flex items-center justify-between gap-4 rounded-2xl border border-[#f0d2c8] bg-white p-4"><p className="text-sm font-semibold text-[#687491]">You can retry, return to the report, or finish.</p><div className="flex gap-2"><ActionButton variant="secondary" onClick={onBack}>Report</ActionButton><ActionButton variant="secondary" onClick={onFinish}>Finish</ActionButton></div></div>}</div></main>;
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

function formatTimestamp(milliseconds: number) {
  const totalSeconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(totalSeconds / 60)).padStart(2, "0")}:${String(totalSeconds % 60).padStart(2, "0")}`;
}
