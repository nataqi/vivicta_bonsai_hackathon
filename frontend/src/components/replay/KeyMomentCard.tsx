"use client";

import type { KeyMoment, useKeyMomentReplay } from "@/hooks/useKeyMomentReplay";

type Replay = ReturnType<typeof useKeyMomentReplay>;

export function KeyMomentCard({
  moment,
  areaLabel,
  replay,
  disabled,
  onPlayOriginal,
  onPlayBetter,
}: {
  moment: KeyMoment;
  areaLabel: string;
  replay: Replay;
  disabled: boolean;
  onPlayOriginal: () => void;
  onPlayBetter: () => void;
}) {
  const strength = moment.kind === "strength";
  const originalLoading = replay.originalStatus === "loading";
  const betterLoading = replay.betterStatus === "loading";
  return (
    <section
      aria-labelledby="key-moment-title"
      className={`mt-4 rounded-[1.5rem] border p-5 sm:p-6 ${strength ? "border-[#cbeadf] bg-[#eefaf6]" : "border-[#f4d9c8] bg-[#fff7f2]"}`}
    >
      <div className="flex flex-wrap items-center gap-3">
        <p className={`text-xs font-bold tracking-[.12em] ${strength ? "text-[#138467]" : "text-[#b4562f]"}`}>YOUR KEY MOMENT</p>
        <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-[#445070]">{areaLabel}</span>
      </div>
      <h2 id="key-moment-title" className="mt-2 text-2xl font-bold tracking-[-.02em] text-[#27325e]">
        {strength ? "A moment that worked well" : "A moment worth a second listen"}
      </h2>
      <p className="mt-2 text-base leading-7 text-[#4d5978]">
        <span className="font-semibold text-[#27325e]">What was happening: </span>
        {moment.customer_context}
      </p>

      <div className="mt-5 flex flex-col gap-3 sm:flex-row">
        <ReplayButton
          playing={replay.playing === "original"}
          loading={originalLoading}
          disabled={disabled || betterLoading}
          onClick={replay.playing === "original" ? replay.stop : onPlayOriginal}
          idleLabel="Hear yourself"
          loadingLabel="Preparing…"
          step="1"
        />
        <ReplayButton
          playing={replay.playing === "better"}
          loading={betterLoading}
          disabled={disabled || originalLoading}
          onClick={replay.playing === "better" ? replay.stop : onPlayBetter}
          idleLabel={strength ? "Hear it even stronger" : "Hear a better take"}
          loadingLabel="Recreating in your voice…"
          step="2"
          accent
        />
      </div>
      {replay.betterStatus === "idle" && (
        <p className="mt-3 text-sm leading-6 text-[#6a7591]">
          The better take uses a temporary copy of your voice. It is deleted when you finish.
        </p>
      )}

      {replay.error && (
        <p role="alert" className="mt-4 rounded-2xl border border-[#f4c5b6] bg-white px-4 py-3 text-sm font-semibold leading-6 text-[#8b452f]">
          {replay.error}
        </p>
      )}

      {replay.betterStatus === "ready" && (
        <div className="mt-5 rounded-2xl bg-white p-4 sm:p-5">
          <p className="text-xs font-bold tracking-[.12em] text-[#5146e5]">{strength ? "EVEN STRONGER" : "A BETTER TAKE"}</p>
          <p className="mt-2 text-xl font-bold leading-8 text-[#27325e]">“{moment.better_answer}”</p>
          <p className="mt-2 text-sm font-semibold leading-6 text-[#4d5978]">{moment.why}</p>
          {replay.voiceMode === "neutral" && (
            <p className="mt-2 text-sm leading-6 text-[#6a7591]">
              Not enough of your voice was captured, so a neutral voice was used.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function ReplayButton({ playing, loading, disabled, onClick, idleLabel, loadingLabel, step, accent = false }: { playing: boolean; loading: boolean; disabled: boolean; onClick: () => void; idleLabel: string; loadingLabel: string; step: string; accent?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
      aria-pressed={playing}
      className={`inline-flex min-h-13 flex-1 items-center justify-center gap-3 rounded-2xl px-5 text-base font-semibold transition focus:outline-none focus:ring-4 focus:ring-[#c9c5ff] disabled:cursor-not-allowed disabled:opacity-60 ${accent ? "bg-[#5146e5] text-white shadow-[0_10px_22px_rgba(81,70,229,.24)] hover:bg-[#4338ca]" : "border border-[#d9def7] bg-white text-[#27325e] hover:bg-[#f4f5ff]"}`}
    >
      <span aria-hidden="true" className={`grid h-7 w-7 place-items-center rounded-full text-xs font-bold ${accent ? "bg-white/20" : "bg-[#eceaff] text-[#5146e5]"}`}>{step}</span>
      <span>{loading ? loadingLabel : playing ? "Stop" : idleLabel}</span>
      <span aria-hidden="true">{loading ? "" : playing ? "■" : "▶"}</span>
    </button>
  );
}
