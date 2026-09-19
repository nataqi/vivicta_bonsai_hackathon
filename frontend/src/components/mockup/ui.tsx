"use client";

import type { ReactNode } from "react";
import type { CoachingFocus } from "@/lib/mockup/data";

export function Mark() {
  return (
    <div className="flex items-center gap-3" aria-label="Compassion Coach">
      <span className="grid h-10 w-10 place-items-center rounded-2xl bg-[#5146e5] text-xl font-bold text-white shadow-[0_8px_18px_rgba(81,70,229,.22)]">C</span>
      <span className="text-lg font-bold tracking-tight text-[#17234a]">Compassion Coach</span>
    </div>
  );
}

export function Shell({ children, compact = false }: { children: ReactNode; compact?: boolean }) {
  return <main className={`min-h-screen bg-[#f7f9ff] px-5 py-5 text-[#17234a] sm:px-8 ${compact ? "" : "lg:px-12"}`}>{children}</main>;
}

export function Button({ children, onClick, variant = "primary", type = "button", disabled = false, className = "" }: { children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "quiet" | "coral"; type?: "button" | "submit"; disabled?: boolean; className?: string }) {
  const variants = {
    primary: "bg-[#5146e5] text-white shadow-[0_10px_22px_rgba(81,70,229,.24)] hover:bg-[#4338ca]",
    secondary: "border border-[#d9def7] bg-white text-[#27325e] hover:bg-[#f4f5ff]",
    quiet: "text-[#5146e5] hover:bg-[#ecebff]",
    coral: "bg-[#f17856] text-white shadow-[0_10px_22px_rgba(241,120,86,.22)] hover:bg-[#df6242]",
  };
  return <button type={type} disabled={disabled} onClick={onClick} className={`inline-flex min-h-12 items-center justify-center rounded-2xl px-5 text-base font-semibold transition focus:outline-none focus:ring-4 focus:ring-[#c9c5ff] disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}>{children}</button>;
}

export function BackControl({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="inline-flex min-h-10 items-center gap-1.5 rounded-xl px-3 text-sm font-semibold text-[#536080] transition hover:bg-white hover:text-[#5146e5] focus:outline-none focus:ring-4 focus:ring-[#dcd9ff]"><span aria-hidden="true">←</span>{label}</button>;
}

export function FocusPill({ focus, selected, onToggle, readOnly = false }: { focus: CoachingFocus; selected: boolean; onToggle?: () => void; readOnly?: boolean }) {
  const content = <><span className={`h-2.5 w-2.5 rounded-full ${selected ? "bg-[#5146e5]" : "bg-[#b8c1d9]"}`} />{focus}</>;
  if (readOnly) return <span className="inline-flex items-center gap-2 rounded-full bg-[#f0efff] px-3 py-2 text-sm font-semibold text-[#4139bd]">{content}</span>;
  return <button type="button" onClick={onToggle} aria-pressed={selected} className={`inline-flex min-h-11 items-center gap-2 rounded-full border px-3.5 py-2 text-left text-sm font-semibold transition ${selected ? "border-[#bbb6ff] bg-[#f0efff] text-[#4139bd]" : "border-[#d8deef] bg-white text-[#52607f] hover:border-[#8c83ff]"}`}>{content}</button>;
}

export function Stepper({ step }: { step: number }) {
  const names = ["Meeting", "Report", "Reflection"];
  return <div className="hidden items-center gap-2 sm:flex" aria-label="Meeting progress">{names.map((name, i) => <div key={name} className="flex items-center gap-2"><span className={`grid h-7 w-7 place-items-center rounded-full text-xs font-bold ${i <= step ? "bg-[#5146e5] text-white" : "bg-[#e3e7f3] text-[#73809f]"}`}>{i + 1}</span><span className={`text-sm font-semibold ${i <= step ? "text-[#38406a]" : "text-[#8a94ad]"}`}>{name}</span>{i < 2 && <span className="mx-1 h-px w-6 bg-[#dce1ee]" />}</div>)}</div>;
}
