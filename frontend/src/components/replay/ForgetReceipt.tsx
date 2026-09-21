"use client";

import { useEffect, useState } from "react";

export type ForgetReceiptData = {
  learningSaved: boolean;
  voice: "none" | "deleted" | "unconfirmed";
};

type Row = { key: string; kind: "deleted" | "kept" | "pending"; label: string };

function rowsFor(data: ForgetReceiptData): Row[] {
  const rows: Row[] = [
    { key: "audio", kind: "deleted", label: "Meeting audio" },
    { key: "transcript", kind: "deleted", label: "Transcript and customer details" },
  ];
  if (data.voice === "deleted") rows.push({ key: "voice", kind: "deleted", label: "Your temporary cloned voice" });
  if (data.voice === "unconfirmed") {
    rows.push({ key: "voice", kind: "pending", label: "Your temporary cloned voice: deletion could not be confirmed and will be retried when the session expires" });
  }
  rows.push(
    data.learningSaved
      ? { key: "learning", kind: "kept", label: "Your generic coaching learning" }
      : { key: "learning", kind: "pending", label: "No coaching learning was saved this time" },
  );
  return rows;
}

const REVEAL_INTERVAL_MS = 450;

/** Shows what was actually removed on Finish and what was kept. */
export function ForgetReceipt({ data, onDismiss }: { data: ForgetReceiptData; onDismiss: () => void }) {
  const rows = rowsFor(data);
  const [visible, setVisible] = useState(0);

  useEffect(() => {
    if (visible >= rows.length) return;
    const timer = window.setTimeout(() => setVisible((current) => current + 1), REVEAL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [visible, rows.length]);

  return (
    <section role="status" aria-label="What was forgotten" className="mt-6 rounded-[1.5rem] border border-[#cbeadf] bg-[#eefaf6] p-5 sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold tracking-[.12em] text-[#138467]">FORGOTTEN</p>
          <h2 className="mt-1 text-xl font-bold text-[#27325e]">The customer conversation is gone.</h2>
        </div>
        <button type="button" onClick={onDismiss} className="rounded-xl px-3 py-1.5 text-sm font-semibold text-[#536080] hover:bg-white focus:outline-none focus:ring-4 focus:ring-[#c9c5ff]">Dismiss</button>
      </div>
      <ul className="mt-4 space-y-2">
        {rows.map((row, index) => (
          <li
            key={row.key}
            className={`flex items-start gap-3 text-base font-semibold text-[#27325e] transition-all duration-500 ${index < visible ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0"}`}
          >
            <span aria-hidden="true" className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold ${row.kind === "kept" ? "bg-[#5146e5] text-white" : row.kind === "deleted" ? "bg-[#16a47e] text-white" : "bg-[#f4d9c8] text-[#8b452f]"}`}>
              {row.kind === "kept" ? "★" : row.kind === "deleted" ? "✓" : "!"}
            </span>
            <span>
              <span className="text-sm font-bold uppercase tracking-wide text-[#5f6c8c]">{row.kind === "kept" ? "Kept · " : row.kind === "deleted" ? "Deleted · " : ""}</span>
              {row.label}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
