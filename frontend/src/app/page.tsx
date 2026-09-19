"use client";

import { useState } from "react";
import { useLiveTranscription, type CoachingArea, type TranscriptionStatus } from "@/hooks/useLiveTranscription";

const COACHING_AREAS: { value: CoachingArea; label: string }[] = [
  { value: "pace_and_pauses", label: "Pace & pauses" },
  { value: "turn_taking_and_interruptions", label: "Turn-taking" },
  { value: "open_questions", label: "Open questions" },
  { value: "acknowledging_emotional_cues", label: "Acknowledge emotion" },
  { value: "stay_before_solving", label: "Stay before solving" },
];

export default function Home() {
  const [focusAreas, setFocusAreas] = useState<CoachingArea[]>(["acknowledging_emotional_cues", "stay_before_solving"]);
  const { status, turns, error, currentNudge, start, stop, isActive } = useLiveTranscription();
  const isListening = status === "listening";

  const toggleFocus = (area: CoachingArea) => {
    if (isActive) return;
    setFocusAreas((current) => current.includes(area) ? current.filter((item) => item !== area) : [...current, area]);
  };

  return (
    <main className="min-h-screen bg-[#f7f9ff] px-5 py-6 text-[#17234a] sm:px-8 lg:px-12">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-6xl flex-col">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-2xl bg-[#5146e5] text-xl font-bold text-white shadow-[0_8px_18px_rgba(81,70,229,.22)]">C</span>
            <div><p className="text-lg font-bold tracking-tight">Compassion Coach</p><p className="text-sm font-medium text-[#687491]">Live meeting coach</p></div>
          </div>
          <StatusBadge status={status} />
        </header>

        <section className="grid flex-1 items-start gap-8 py-10 lg:grid-cols-[.9fr_1.1fr]">
          <div className="flex flex-col items-start lg:sticky lg:top-8">
            <p className="text-sm font-bold tracking-[.12em] text-[#5146e5]">LIVE COACHING</p>
            <h1 className="mt-3 max-w-xl text-4xl font-bold tracking-[-.04em] sm:text-5xl">Stay present in the conversation.</h1>
            <p className="mt-5 max-w-lg text-lg leading-8 text-[#5d6884]">Choose what you want to practise. The coach listens quietly and steps in only when useful.</p>

            <fieldset className="mt-7 max-w-xl" disabled={isActive}>
              <legend className="text-sm font-bold text-[#34405f]">Coaching focus</legend>
              <div className="mt-3 flex flex-wrap gap-2">
                {COACHING_AREAS.map((area) => {
                  const selected = focusAreas.includes(area.value);
                  return <button key={area.value} type="button" aria-pressed={selected} onClick={() => toggleFocus(area.value)} className={`rounded-full border px-3.5 py-2 text-sm font-semibold transition ${selected ? "border-[#7770e8] bg-[#eceaff] text-[#332b9d]" : "border-[#dfe4f3] bg-white text-[#65708d] hover:border-[#b9b5f6]"} disabled:cursor-default disabled:opacity-80`}>{area.label}</button>;
                })}
              </div>
            </fieldset>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              {!isActive ? <button type="button" onClick={() => void start(focusAreas)} className="inline-flex min-h-13 items-center justify-center rounded-2xl bg-[#5146e5] px-6 text-base font-semibold text-white shadow-[0_10px_22px_rgba(81,70,229,.24)] transition hover:bg-[#4338ca] focus:outline-none focus:ring-4 focus:ring-[#c9c5ff]">Start meeting</button> : <button type="button" onClick={stop} disabled={status === "stopping"} className="inline-flex min-h-13 items-center justify-center rounded-2xl bg-[#f17856] px-6 text-base font-semibold text-white shadow-[0_10px_22px_rgba(241,120,86,.22)] transition hover:bg-[#df6242] focus:outline-none focus:ring-4 focus:ring-[#ffd4c8] disabled:cursor-wait disabled:opacity-65">{status === "stopping" ? "Finishing…" : "End meeting"}</button>}
              <p className="text-sm font-medium text-[#707c98]" aria-live="polite">{statusMessage(status)}</p>
            </div>

            {error && <div role="alert" className="mt-5 max-w-lg rounded-2xl border border-[#f4c5b6] bg-[#fff3ef] px-4 py-3 text-sm font-semibold leading-6 text-[#8b452f]">{error}</div>}

            <div className="mt-8 flex w-full max-w-lg items-center gap-4 rounded-2xl border border-[#dfe4f3] bg-white px-4 py-3 shadow-sm">
              <span className={`grid h-12 w-12 place-items-center rounded-full text-xl ${isListening ? "animate-pulse bg-[#dcf8ef] text-[#138467]" : "bg-[#eef0f7] text-[#75819e]"}`} aria-hidden="true">◉</span>
              <div><p className="font-bold text-[#34405f]">{isListening ? "Listening and coaching" : "Microphone inactive"}</p><p className="mt-0.5 text-sm text-[#707c98]">Audio, transcript, and coaching context are temporary.</p></div>
            </div>
          </div>

          <div className="space-y-5">
            <section className="min-h-44 rounded-[1.7rem] border border-[#d8d5ff] bg-gradient-to-br from-[#f0efff] via-[#f5f4ff] to-[#edf5ff] p-6 shadow-[0_18px_45px_rgba(81,70,229,.10)]" aria-live="polite">
              <p className="text-xs font-bold tracking-[.12em] text-[#5146e5]">LIVE COACH</p>
              {currentNudge ? <div className="mt-5 border-l-4 border-[#7770e8] pl-5"><p className="text-2xl font-bold leading-9 text-[#17234a]">{currentNudge.text}</p><p className="mt-2 text-sm font-semibold text-[#665fb8]">A small moment to try now</p></div> : <div className="mt-5"><p className="text-xl font-bold text-[#28345b]">{isListening ? "Listening quietly…" : "Your next nudge will appear here."}</p><p className="mt-2 leading-7 text-[#6b7591]">The coach stays silent unless there is a clear, useful prompt.</p></div>}
            </section>

            <details className="overflow-hidden rounded-[1.7rem] border border-[#dfe4f3] bg-white shadow-[0_16px_40px_rgba(48,59,113,.07)]">
              <summary className="cursor-pointer px-5 py-4 text-sm font-bold text-[#5146e5] sm:px-6">Debug transcript · {turns.length} finalized turns</summary>
              <div className="max-h-[30rem] overflow-y-auto border-t border-[#e7eaf4] p-5 sm:p-6" aria-live="polite">
                {turns.length === 0 ? <p className="py-12 text-center font-medium text-[#7a86a1]">No finalized turns yet.</p> : <ol className="space-y-4">{turns.map((turn) => <li key={turn.id} className={`rounded-2xl border p-4 ${turn.speaker === "advisor" ? "border-[#d4d1ff] bg-[#f3f1ff]" : "border-[#cbeadf] bg-[#eefaf6]"}`}><div className="flex items-center justify-between gap-4"><p className={`text-xs font-bold uppercase tracking-[.1em] ${turn.speaker === "advisor" ? "text-[#5146e5]" : "text-[#138467]"}`}>{turn.speaker}</p><p className="text-xs font-semibold text-[#8a94ad]">{formatTimestamp(turn.startTimeMs)}</p></div><p className="mt-2 text-base font-medium leading-7 text-[#2f3a5d]">{turn.text}</p></li>)}</ol>}
              </div>
            </details>
          </div>
        </section>
      </div>
    </main>
  );
}

function StatusBadge({ status }: { status: TranscriptionStatus }) {
  const active = status === "listening";
  return <div className="flex items-center gap-2 rounded-full border border-[#e1e5f2] bg-white px-4 py-2.5 text-sm font-bold shadow-sm"><span className={`h-2.5 w-2.5 rounded-full ${active ? "animate-pulse bg-[#16a47e]" : "bg-[#a6afc3]"}`} />{active ? "Listening" : statusLabel(status)}</div>;
}

function statusLabel(status: TranscriptionStatus) {
  return { idle: "Ready", requesting: "Requesting microphone", connecting: "Connecting", listening: "Listening", stopping: "Finishing", stopped: "Stopped", error: "Needs attention" }[status];
}

function statusMessage(status: TranscriptionStatus) {
  return { idle: "Ready when you are.", requesting: "Waiting for microphone permission…", connecting: "Connecting securely…", listening: "Speak naturally. Coaching is active.", stopping: "Finalizing the last words…", stopped: "Session ended. You can start another.", error: "Resolve the message below, then try again." }[status];
}

function formatTimestamp(milliseconds: number) {
  const totalSeconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(totalSeconds / 60)).padStart(2, "0")}:${String(totalSeconds % 60).padStart(2, "0")}`;
}
