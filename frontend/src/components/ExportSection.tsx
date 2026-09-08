"use client";

import { useState } from "react";
import { downloadUrl, isJobActive, type Job, type ProjectState } from "@/lib/api";

interface ExportSectionProps {
  project: ProjectState;
  onSubmit: () => Promise<Job>;
  job?: Job | null;
}

/** Job fallito (dell'ultima esecuzione nota): mostra l'errore tecnico. */
function JobError({ job }: { job: Job }) {
  if (job.status !== "failed") return null;
  return (
    <p className="rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">
      Rendering fallito: {job.error ?? "errore sconosciuto"}
    </p>
  );
}

function formatBytes(n: number): string {
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

const CHECK_LABEL: Record<string, string> = {
  duration: "Durata",
  av_sync: "Sync A/V",
  verticals: "Verticali",
  transitions: "Transizioni",
};

/** Verdetto QA: approvato o lista problemi con agente destinatario. */
function QAVerdict({ project }: { project: ProjectState }) {
  const qa = project.qa_report;
  if (!qa) return null;
  if (qa.status === "approved") {
    return (
      <p className="text-sm text-emerald-300" title={qa.checks.map(c => `${c.name}: ${c.detail}`).join("\n")}>
        ✓ QA superato — durata, sync, verticali, transizioni
      </p>
    );
  }
  return (
    <div className="rounded-lg border border-amber-700 bg-amber-900/20 p-3">
      <p className="mb-1 text-sm font-medium text-amber-300">
        QA: {qa.issues.length} problemi da correggere
      </p>
      <ul className="space-y-1 text-xs text-amber-200">
        {qa.issues.map((issue, i) => (
          <li key={i}>
            <strong>{CHECK_LABEL[issue.check] ?? issue.check}:</strong> {issue.message}{" "}
            <span className="text-amber-400/80">(→ {issue.route_to})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** M5 + coda: submit in background, progress live dal job, player finale. */
export function ExportSection({ project, onSubmit, job }: ExportSectionProps) {
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const manifest = project.render_manifest;
  const done = manifest?.status === "done";
  const active = isJobActive(job);
  const busy = submitting || active;
  const src = downloadUrl(project.project_id);

  const handleClick = async () => {
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Esportazione fallita");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section aria-label="Esportazione video" className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
          Video finale
        </h3>
        <button
          type="button"
          disabled={busy || project.media.length === 0}
          onClick={handleClick}
          className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
        >
          {busy ? "Rendering…" : done ? "↻ Riesporta" : "🎬 Esporta video"}
        </button>
      </div>

      {error && (
        <p className="mb-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">
          {error}
        </p>
      )}

      {job && <JobError job={job} />}

      {active && job && (
        <div className="mb-3 space-y-1" aria-label="Avanzamento rendering">
          <div className="h-2 overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all duration-500"
              style={{ width: `${Math.round(job.progress.fraction * 100)}%` }}
            />
          </div>
          <p className="text-xs text-slate-400">
            {job.status === "queued"
              ? "In coda…"
              : `${job.progress.stage} — ${Math.round(job.progress.fraction * 100)}%${job.progress.note ? ` · ${job.progress.note}` : ""}`}
          </p>
        </div>
      )}

      {done && manifest ? (
        <div className="space-y-3">
          <video
            key={manifest.output.rendered_at ?? manifest.total_sec}
            controls
            preload="metadata"
            src={src}
            className="aspect-video w-full rounded-lg bg-black"
          />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-300">
            <span>{manifest.total_sec.toFixed(1)}s</span>
            <span>{manifest.output.resolution} · {manifest.output.fps}fps</span>
            {manifest.output.size_bytes ? <span>{formatBytes(manifest.output.size_bytes)}</span> : null}
            <a
              href={src}
              download={`video-${project.project_id}.mp4`}
              className="text-emerald-400 hover:underline"
            >
              ⬇ Scarica mp4
            </a>
          </div>
          <QAVerdict project={project} />
        </div>
      ) : (
        !error && !busy && (
          <p className="text-sm text-slate-500">
            L&apos;esportazione monta il video in mp4 ({project.output_spec.vcodec.toUpperCase()})
            in background: puoi continuare a lavorare, l&apos;anteprima appare da sola.
          </p>
        )
      )}
    </section>
  );
}
