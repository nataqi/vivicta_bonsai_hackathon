"use client";

import { useLiveTranscription, type TranscriptionStatus } from "@/hooks/useLiveTranscription";

export default function Home() {
  const { status, turns, error, start, stop, isActive } = useLiveTranscription();
  const isListening = status === "listening";

  return (
    <main className="min-h-screen bg-[#f7f9ff] px-5 py-6 text-[#17234a] sm:px-8 lg:px-12">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-6xl flex-col">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-2xl bg-[#5146e5] text-xl font-bold text-white shadow-[0_8px_18px_rgba(81,70,229,.22)]">
              C
            </span>
            <div>
              <p className="text-lg font-bold tracking-tight">Compassion Coach</p>
              <p className="text-sm font-medium text-[#687491]">Live transcription check</p>
            </div>
          </div>
          <StatusBadge status={status} />
        </header>

        <section className="grid flex-1 items-center gap-8 py-10 lg:grid-cols-[.8fr_1.2fr]">
          <div className="flex flex-col items-start">
            <p className="text-sm font-bold tracking-[.12em] text-[#5146e5]">SLICE 1</p>
            <h1 className="mt-3 max-w-xl text-4xl font-bold tracking-[-.04em] sm:text-5xl">
              Listen to the conversation, live.
            </h1>
            <p className="mt-5 max-w-lg text-lg leading-8 text-[#5d6884]">
              Speak naturally with two people in the room. Finalized turns appear here only for this session.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              {!isActive ? (
                <button
                  type="button"
                  onClick={() => void start()}
                  className="inline-flex min-h-13 items-center justify-center rounded-2xl bg-[#5146e5] px-6 text-base font-semibold text-white shadow-[0_10px_22px_rgba(81,70,229,.24)] transition hover:bg-[#4338ca] focus:outline-none focus:ring-4 focus:ring-[#c9c5ff]"
                >
                  Start transcription
                </button>
              ) : (
                <button
                  type="button"
                  onClick={stop}
                  disabled={status === "stopping"}
                  className="inline-flex min-h-13 items-center justify-center rounded-2xl bg-[#f17856] px-6 text-base font-semibold text-white shadow-[0_10px_22px_rgba(241,120,86,.22)] transition hover:bg-[#df6242] focus:outline-none focus:ring-4 focus:ring-[#ffd4c8] disabled:cursor-wait disabled:opacity-65"
                >
                  {status === "stopping" ? "Finishing…" : "Stop transcription"}
                </button>
              )}
              <p className="text-sm font-medium text-[#707c98]" aria-live="polite">
                {statusMessage(status)}
              </p>
            </div>

            {error && (
              <div
                role="alert"
                className="mt-5 max-w-lg rounded-2xl border border-[#f4c5b6] bg-[#fff3ef] px-4 py-3 text-sm font-semibold leading-6 text-[#8b452f]"
              >
                {error}
              </div>
            )}

            <div className="mt-10 flex items-center gap-4 rounded-2xl border border-[#dfe4f3] bg-white px-4 py-3 shadow-sm">
              <span
                className={`grid h-12 w-12 place-items-center rounded-full text-xl ${
                  isListening ? "animate-pulse bg-[#dcf8ef] text-[#138467]" : "bg-[#eef0f7] text-[#75819e]"
                }`}
                aria-hidden="true"
              >
                ◉
              </span>
              <div>
                <p className="font-bold text-[#34405f]">
                  {isListening ? "Microphone active" : "Microphone inactive"}
                </p>
                <p className="mt-0.5 text-sm text-[#707c98]">Audio and transcript are not stored.</p>
              </div>
            </div>
          </div>

          <section className="overflow-hidden rounded-[1.7rem] border border-[#dfe4f3] bg-white shadow-[0_20px_55px_rgba(48,59,113,.09)]">
            <div className="flex items-center justify-between border-b border-[#e7eaf4] px-5 py-4 sm:px-6">
              <div>
                <p className="text-xs font-bold tracking-[.12em] text-[#5146e5]">FINALIZED TURNS</p>
                <h2 className="mt-1 text-xl font-bold">Temporary transcript</h2>
              </div>
              <span className="rounded-full bg-[#f0efff] px-3 py-1.5 text-sm font-bold text-[#5146e5]">
                {turns.length}
              </span>
            </div>

            <div className="h-[32rem] overflow-y-auto p-5 sm:p-6" aria-live="polite">
              {turns.length === 0 ? (
                <div className="grid h-full place-items-center text-center">
                  <div className="max-w-sm">
                    <p className="text-lg font-bold text-[#445070]">
                      {isListening ? "Listening for a completed turn…" : "No transcript yet"}
                    </p>
                    <p className="mt-2 leading-7 text-[#7a86a1]">
                      The adviser should speak first, then pause before the customer replies.
                    </p>
                  </div>
                </div>
              ) : (
                <ol className="space-y-4">
                  {turns.map((turn) => (
                    <li
                      key={turn.id}
                      className={`rounded-2xl border p-4 ${
                        turn.speaker === "advisor"
                          ? "border-[#d4d1ff] bg-[#f3f1ff]"
                          : "border-[#cbeadf] bg-[#eefaf6]"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-4">
                        <p
                          className={`text-xs font-bold uppercase tracking-[.1em] ${
                            turn.speaker === "advisor" ? "text-[#5146e5]" : "text-[#138467]"
                          }`}
                        >
                          {turn.speaker}
                        </p>
                        <p className="text-xs font-semibold text-[#8a94ad]">
                          {formatTimestamp(turn.startTimeMs)}
                        </p>
                      </div>
                      <p className="mt-2 text-base font-medium leading-7 text-[#2f3a5d]">{turn.text}</p>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </section>
        </section>
      </div>
    </main>
  );
}

function StatusBadge({ status }: { status: TranscriptionStatus }) {
  const active = status === "listening";
  return (
    <div className="flex items-center gap-2 rounded-full border border-[#e1e5f2] bg-white px-4 py-2.5 text-sm font-bold shadow-sm">
      <span className={`h-2.5 w-2.5 rounded-full ${active ? "animate-pulse bg-[#16a47e]" : "bg-[#a6afc3]"}`} />
      {active ? "Listening" : statusLabel(status)}
    </div>
  );
}

function statusLabel(status: TranscriptionStatus) {
  const labels: Record<TranscriptionStatus, string> = {
    idle: "Ready",
    requesting: "Requesting microphone",
    connecting: "Connecting",
    listening: "Listening",
    stopping: "Finishing",
    stopped: "Stopped",
    error: "Needs attention",
  };
  return labels[status];
}

function statusMessage(status: TranscriptionStatus) {
  const messages: Record<TranscriptionStatus, string> = {
    idle: "Ready when you are.",
    requesting: "Waiting for microphone permission…",
    connecting: "Connecting securely to transcription…",
    listening: "Speak naturally and pause between turns.",
    stopping: "Finalizing the last words…",
    stopped: "Session ended. You can start another.",
    error: "Resolve the message below, then try again.",
  };
  return messages[status];
}

function formatTimestamp(milliseconds: number) {
  const totalSeconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}
