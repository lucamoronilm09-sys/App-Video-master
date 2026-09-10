"use client";

import { useState } from "react";
import type { ProjectState } from "@/lib/api";

interface Props { project: ProjectState; onSubmit: (rating: "up" | "down", reasons: string[], note: string) => Promise<void>; busy?: boolean; }
const REASONS = ["Troppo veloce", "Troppo lento", "Foto sbagliate", "Poche persone", "Musica non adatta", "Transizioni", "Ordine delle scene"];

export function AIFeedback({ project, onSubmit, busy }: Props) {
  const [selected, setSelected] = useState<string[]>(project.ai_feedback?.reasons ?? []);
  const [note, setNote] = useState(project.ai_feedback?.note ?? "");
  const [sent, setSent] = useState(false);
  const toggle = (reason: string) => setSelected(v => v.includes(reason) ? v.filter(x => x !== reason) : [...v, reason]);
  const send = async (rating: "up" | "down") => { await onSubmit(rating, selected, note); setSent(true); };
  return <section aria-label="Feedback sul montaggio IA" className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Insegna all'AI</h3><p className="mt-1 text-xs text-slate-500">Il feedback viene conservato nello storico del progetto e accompagna le revisioni.</p></div>{sent && <span className="text-xs text-emerald-300">Feedback salvato</span>}</div>
    <div className="mt-4 flex flex-wrap gap-2">{REASONS.map(r => <button key={r} type="button" disabled={busy} onClick={() => toggle(r)} className={`rounded-full border px-3 py-1.5 text-xs transition ${selected.includes(r) ? "border-violet-400/50 bg-violet-400/15 text-violet-200" : "border-white/10 bg-white/5 text-slate-400 hover:text-slate-200"}`}>{r}</button>)}</div>
    <textarea value={note} maxLength={1000} disabled={busy} onChange={e => setNote(e.target.value)} placeholder="Nota facoltativa: cosa cambieresti nel montaggio?" rows={2} className="mt-3 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600" />
    <div className="mt-3 flex flex-wrap gap-2"><button type="button" disabled={busy} onClick={() => void send("up")} className="rounded-xl bg-emerald-600/80 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500">👍 Mi piace</button><button type="button" disabled={busy} onClick={() => void send("down")} className="rounded-xl bg-rose-600/70 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-500">👎 Da migliorare</button></div>
  </section>;
}
