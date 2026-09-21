"use client";

import { useEffect, useState } from "react";
import { BackControl, Button, FocusPill, Mark, Shell, Stepper } from "@/components/mockup/ui";
import { coachingDimensions, defaultFocus, liveNudges, mockCoachingInsights, type CoachingFocus } from "@/lib/mockup/data";
import styles from "./listening.module.css";

type View = "home" | "meeting" | "report" | "reflection";
type Chat = { author: "coach" | "advisor"; text: string };
const initialReflection: Chat[] = [{ author: "coach", text: "How do you think the meeting went?" }];

export default function MockupPage() {
  const [view, setView] = useState<View>("home");
  const [focus, setFocus] = useState<CoachingFocus[]>(defaultFocus);
  const [seconds, setSeconds] = useState(0);
  const [nudgeIndex, setNudgeIndex] = useState(-1);
  const [updated, setUpdated] = useState(false);
  const [chat, setChat] = useState<Chat[]>(initialReflection);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    if (view !== "meeting") return;
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [view]);
  useEffect(() => {
    if (view !== "meeting") return;
    const nudge = window.setTimeout(() => setNudgeIndex(0), 3500);
    return () => window.clearTimeout(nudge);
  }, [view]);
  useEffect(() => {
    if (view !== "meeting" || nudgeIndex < 0 || nudgeIndex >= liveNudges.length - 1) return;
    const next = window.setTimeout(() => setNudgeIndex((value) => value + 1), 8500);
    return () => window.clearTimeout(next);
  }, [view, nudgeIndex]);

  const toggleFocus = (item: CoachingFocus) => setFocus((current) => current.includes(item) ? current.filter((focusItem) => focusItem !== item) : [...current, item]);
  const clock = `00:${String(seconds).padStart(2, "0")}`;
  const currentNudge = nudgeIndex >= 0 ? liveNudges[nudgeIndex] : null;
  function startMeeting() {
    if (focus.length === 0) return;
    setSeconds(0);
    setNudgeIndex(-1);
    setChat(initialReflection);
    setDraft("");
    setView("meeting");
  }
  function leaveMeeting() {
    setSeconds(0);
    setNudgeIndex(-1);
    setView("home");
  }

  function sendReflection(text: string) {
    const answer = text.trim(); if (!answer) return;
    const advisorReplies = chat.filter((message) => message.author === "advisor").length;
    if (advisorReplies >= 2) return;
    const followUp = advisorReplies === 0
      ? "That matches one moment I noticed too. You moved toward a solution quite quickly. What could you try before offering a solution next time?"
      : "That sounds like a thoughtful adjustment. A short pause and acknowledgement can give the customer space before you move into solutions.";
    setChat((current) => [...current, { author: "advisor", text: answer }, { author: "coach", text: followUp }]);
    setDraft("");
  }
  function finish() { setUpdated(true); setView("home"); }

  if (view === "home") return <Home focus={focus} updated={updated} onToggle={toggleFocus} onStart={startMeeting} />;
  if (view === "meeting") return <Meeting clock={clock} focus={focus} nudge={currentNudge} onBack={leaveMeeting} onEnd={() => setView("report")} />;
  if (view === "report") return <Report focus={focus} onHome={finish} onFinish={finish} />;
  return <Reflection chat={chat} draft={draft} setDraft={setDraft} onSend={sendReflection} onBack={() => setView("report")} onFinish={finish} />;
}

function Home({ focus, updated, onToggle, onStart }: { focus: CoachingFocus[]; updated: boolean; onToggle: (focus: CoachingFocus) => void; onStart: () => void }) {
  const insight = updated ? mockCoachingInsights.improvement : mockCoachingInsights["stable-positive-pattern"];

  return <Shell><div className="mx-auto max-w-5xl"><header className="flex items-center justify-between py-2"><Mark /><span className="rounded-full border border-[#e2e6f4] bg-white px-4 py-2 text-sm font-semibold text-[#536080]">Your private coach</span></header><section className="py-12 sm:py-14"><p className="text-sm font-bold tracking-[.12em] text-[#5146e5]">GOOD MORNING, ALEX</p><h1 className="mt-3 text-3xl font-bold tracking-[-.035em] text-[#17234a] sm:text-4xl">Ready for your next conversation?</h1><Button onClick={onStart} disabled={focus.length === 0} className="mt-7 px-7">Start a meeting <span className="ml-2 text-xl">→</span></Button></section><section className="grid gap-5 pb-8 lg:grid-cols-[1.05fr_.95fr]"><div className="rounded-[1.7rem] border border-[#dfe4f3] bg-white p-6 sm:p-7"><p className="text-sm font-bold tracking-[.1em] text-[#5146e5]">CURRENT FOCUS</p><h2 className="mt-2 text-xl font-bold text-[#26315a]">What gets extra attention</h2><div className="mt-6 flex flex-wrap gap-2.5">{coachingDimensions.map(({ label }) => <FocusPill key={label} focus={label} selected={focus.includes(label)} onToggle={() => onToggle(label)} />)}</div><p className="mt-5 text-sm leading-6 text-[#687491]">Select one or more areas for your next meeting.</p></div><div className="rounded-[1.7rem] border border-[#cedcff] bg-[#eaf1ff] p-6 sm:p-7"><p className="text-sm font-bold tracking-[.1em] text-[#3557b7]">RECENT COACHING INSIGHT</p><p className="mt-3 text-xl font-bold leading-8 text-[#1e315e]">{insight.observation}</p><div className="mt-5 border-t border-[#cad8f5] pt-4"><p className="text-sm font-bold text-[#344a80]">Keep exploring</p><p className="mt-1 text-base leading-7 text-[#435a83]">{insight.keepExploring}</p></div></div></section></div></Shell>;
}

function Meeting({ clock, focus, nudge, onBack, onEnd }: { clock: string; focus: CoachingFocus[]; nudge: string | null; onBack: () => void; onEnd: () => void }) {
  return (
    <Shell>
      <div className="mx-auto flex min-h-[calc(100vh-2.5rem)] max-w-6xl flex-col">
        <header className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3"><Mark /><BackControl label="Home" onClick={onBack} /></div>
          <div className="flex items-center gap-3 rounded-full bg-white px-4 py-2.5 text-sm font-bold shadow-sm"><span className="h-2.5 w-2.5 animate-pulse rounded-full bg-[#16a47e]" />Meeting in progress <span className="ml-2 text-[#687491]">{clock}</span></div>
        </header>
        <div className="flex flex-1 flex-col items-center justify-center py-12">
          <div className="relative isolate grid h-36 w-36 place-items-center rounded-full bg-[#e7e5ff]">
            <span className={styles.ring} aria-hidden="true" />
            <span className={styles.ring} aria-hidden="true" />
            <span className={styles.ring} aria-hidden="true" />
            <div className="relative z-10 grid h-20 w-20 place-items-center rounded-full bg-[#5146e5] text-3xl text-white shadow-[0_10px_28px_rgba(81,70,229,.22)]">⌁</div>
            <span className="absolute -bottom-14 z-10 whitespace-nowrap text-base font-semibold text-[#5d6884]">Your coach is listening quietly</span>
          </div>
          <div className="mt-28 min-h-28 text-center">{nudge ? <div key={nudge} className="rounded-[1.6rem] border border-[#c9c5ff] bg-[#f0efff] px-8 py-6 shadow-[0_18px_45px_rgba(81,70,229,.12)]"><p className="text-2xl font-bold text-[#27325e]">{nudge}</p></div> : <p className="text-lg text-[#8490aa]">Making room for the conversation…</p>}</div>
        </div>
        <footer className="flex flex-col items-center justify-between gap-5 rounded-[1.7rem] border border-[#e1e5f2] bg-white p-5 sm:flex-row sm:px-7"><div><p className="text-sm font-bold text-[#445070]">Today’s focus</p><p className="mt-1 text-sm text-[#707c98]">{focus.length ? focus.join(" · ") : "All coaching dimensions"}</p></div><Button variant="coral" onClick={onEnd}>End meeting</Button></footer>
      </div>
    </Shell>
  );
}

function Report({ focus, onHome, onFinish }: { focus: CoachingFocus[]; onHome: () => void; onFinish: () => void }) {
  return (
    <Shell>
      <div className="mx-auto max-w-5xl">
        <header className="flex items-center justify-between gap-4 py-2">
          <div className="flex items-center gap-3"><Mark /><BackControl label="Home" onClick={onHome} /></div>
          <Stepper step={1} />
        </header>

        <div className="mt-7 text-center">
          <h1 className="text-3xl font-bold tracking-[-.035em] sm:text-4xl">A few things to carry forward.</h1>
        </div>

        <section className="mt-7 grid gap-4 md:grid-cols-2">
          <article className="rounded-[1.5rem] border border-[#cedcff] bg-[#eef3ff] p-5 sm:p-6">
            <p className="text-sm font-bold tracking-wide text-[#4059b8]">WHAT WENT WELL</p>
            <h2 className="mt-2 text-xl font-bold text-[#27325e]">You gave the customer space to explain.</h2>
            <p className="mt-2 text-base leading-6 text-[#5d6887]">You used open questions and did not rush to respond.</p>
          </article>
          <article className="rounded-[1.5rem] border border-[#d8d3ff] bg-[#f3f0ff] p-5 sm:p-6">
            <p className="text-sm font-bold tracking-wide text-[#5146e5]">TRY NEXT TIME</p>
            <h2 className="mt-2 text-xl font-bold text-[#302d66]">Pause with uncertainty before solving.</h2>
            <p className="mt-2 text-base leading-6 text-[#66628b]">Give the concern a moment before moving into solutions.</p>
          </article>
        </section>

        <section className="mt-4 grid gap-4 rounded-[1.4rem] border border-[#dfe4f3] bg-white p-5 sm:grid-cols-[1fr_1.15fr] sm:items-center sm:gap-0">
          <div className="sm:pr-6">
            <p className="text-xs font-bold tracking-[.12em] text-[#5146e5]">YOUR FOCUS TODAY</p>
            <p className="mt-1.5 text-sm font-semibold leading-5 text-[#445070]">{focus.join(" · ")}</p>
          </div>
          <div className="border-t border-[#e7eaf4] pt-4 sm:border-l sm:border-t-0 sm:py-1 sm:pl-6">
            <p className="text-xs font-bold tracking-[.12em] text-[#5146e5]">TAKEAWAY</p>
            <p className="mt-1.5 text-sm font-semibold leading-5 text-[#445070]">Pause, acknowledge, then move toward a solution.</p>
          </div>
        </section>

        <div className="mt-5 flex justify-center">
          <Button variant="secondary" onClick={onFinish}>Finish</Button>
        </div>
      </div>
    </Shell>
  );
}

function Reflection({ chat, draft, setDraft, onSend, onBack, onFinish }: { chat: Chat[]; draft: string; setDraft: (value: string) => void; onSend: (value: string) => void; onBack: () => void; onFinish: () => void }) {
  const isComplete = chat.filter((message) => message.author === "advisor").length >= 2;

  return (
    <Shell>
      <div className="mx-auto max-w-3xl">
        <header className="flex items-center justify-between gap-4 py-2">
          <div className="flex items-center gap-3"><Mark /><BackControl label="Report" onClick={onBack} /></div>
          <Stepper step={2} />
        </header>

        <section className="mt-7 overflow-hidden rounded-[1.7rem] bg-white shadow-[0_20px_55px_rgba(48,59,113,.09)]">
          <div className="border-b border-[#ebedf5] px-6 py-5 sm:px-7">
            <p className="text-sm font-bold tracking-wide text-[#5146e5]">A SHORT REFLECTION</p>
            <h1 className="mt-1 text-2xl font-bold tracking-[-.03em]">Make the learning your own.</h1>
          </div>
          <div className="space-y-3 p-5 sm:p-6">
            {chat.map((message, index) => (
              <div key={`${message.author}-${index}`} className={`flex ${message.author === "advisor" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[88%] rounded-[1.25rem] px-4 py-3 text-sm leading-6 sm:text-base ${message.author === "advisor" ? "rounded-br-md bg-[#5146e5] text-white" : "rounded-bl-md bg-[#eef0ff] text-[#29345f]"}`}>
                  {message.author === "coach" && <p className="mb-1 text-xs font-bold tracking-wide text-[#5146e5]">YOUR COACH</p>}
                  {message.text}
                </div>
              </div>
            ))}
          </div>
          {!isComplete && (
            <div className="border-t border-[#ebedf5] bg-[#fbfcff] p-4 sm:p-5">
              <form onSubmit={(event) => { event.preventDefault(); onSend(draft); }} className="flex gap-3">
                <label className="sr-only" htmlFor="reflection">Your reflection</label>
                <input id="reflection" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Write your reflection…" className="min-h-12 flex-1 rounded-2xl border border-[#dce1ee] bg-white px-4 text-base outline-none placeholder:text-[#8a94ad] focus:border-[#5146e5] focus:ring-4 focus:ring-[#e5e3ff]" />
                <Button type="submit" disabled={!draft.trim()}>Send</Button>
              </form>
            </div>
          )}
        </section>

        {isComplete && (
          <section className="mt-4 flex flex-col items-start justify-between gap-4 rounded-[1.4rem] border border-[#cedcff] bg-[#eef3ff] p-5 sm:flex-row sm:items-center">
            <div>
              <p className="text-xs font-bold tracking-[.12em] text-[#4059b8]">TAKEAWAY FOR NEXT TIME</p>
              <p className="mt-1 text-base font-bold text-[#27325e]">Next meeting: pause and acknowledge the concern before moving into solutions.</p>
            </div>
            <Button variant="secondary" onClick={onFinish}>Finish</Button>
          </section>
        )}
      </div>
    </Shell>
  );
}
