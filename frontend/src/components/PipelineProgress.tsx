"use client";

import type { PipelineEvent } from "@/lib/api";

const STAGES: { id: string; label: string }[] = [
  { id: "drive_import", label: "Drive" },
  { id: "intake", label: "Intake" },
  { id: "normalizer", label: "Normalizer" },
  { id: "sequence", label: "Sequence" },
  { id: "audio_analysis", label: "Audio" },
  { id: "edit_director", label: "Regia" },
  { id: "timeline_compiler", label: "Compiler" },
  { id: "render", label: "Render" },
  { id: "qa", label: "QA" },
];

type StageState = "pending" | "running" | "done" | "failed";

function stageState(log: PipelineEvent[], stage: string): StageState {
  const entries = log.filter(e => e.stage === stage);
  if (entries.some(e => e.status === "failed")) return "failed";
  if (entries.some(e => e.status === "running")) return "running";
  if (entries.some(e => e.status === "done")) return "done";
  return "pending";
}

const DOT: Record<StageState, string> = {
  pending: "bg-slate-700",
  running: "bg-amber-400 animate-pulse",
  done: "bg-emerald-400",
  failed: "bg-rose-500",
};

/** M8: barra di avanzamento pipeline in tempo reale (da SSE). */
export function PipelineProgress({ log }: { log: PipelineEvent[] }) {
  if (log.length === 0) return null;
  return (
    <ol aria-label="Avanzamento pipeline" className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2.5">
      {STAGES.map(s => {
        const st = stageState(log, s.id);
        return (
          <li key={s.id} className="flex items-center gap-1.5 text-xs" title={`${s.label}: ${st}`}>
            <span className={`h-2 w-2 rounded-full ${DOT[st]}`} />
            <span className={st === "pending" ? "text-slate-600" : st === "failed" ? "text-rose-300" : "text-slate-300"}>
              {s.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
