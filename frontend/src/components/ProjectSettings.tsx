"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getProject, updateProject, type BackgroundFill, type MediaItem, type OutputSpec } from "@/lib/api";

interface ProjectSettingsProps {
  spec: OutputSpec;
  onSave: (patch: { background_fill?: BackgroundFill; resolution?: string; fps?: number; vcodec?: "h264" | "h265" }) => Promise<void>;
  busy?: boolean;
  /** Media del progetto: serve a consigliare un fps senza conversioni a scatti. */
  media?: MediaItem[];
}

const RESOLUTIONS = ["1280x720", "1920x1080", "3840x2160"];
const FPS_OPTIONS = [23, 24, 25, 29, 30, 50, 59, 60];

function dominantSourceFps(media: MediaItem[] | undefined): number | null {
  const rates = (media ?? [])
    .filter(m => m.type === "video" && typeof m.source_fps === "number")
    .map(m => m.source_fps as number);
  if (rates.length === 0) return null;
  const rounded = rates.map(r => Math.round(r));
  if (new Set(rounded).size !== 1) return null;
  return Math.round(rates.reduce((a, b) => a + b, 0) / rates.length);
}

export function ProjectSettings({ spec, onSave, busy, media }: ProjectSettingsProps) {
  const params = useParams();
  const projectId = params.id as string;
  const srcFps = dominantSourceFps(media);
  const [projectName, setProjectName] = useState("Nuovo progetto");
  const [nameDraft, setNameDraft] = useState("");
  const [nameBusy, setNameBusy] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getProject(projectId)
      .then(project => {
        if (!cancelled) {
          const name = project.name || "Nuovo progetto";
          setProjectName(name);
          setNameDraft(name);
        }
      })
      .catch(() => null);
    return () => { cancelled = true; };
  }, [projectId]);

  const mismatch =
    srcFps !== null &&
    Math.abs(srcFps - spec.fps) > 1 &&
    !(srcFps === 25 && spec.fps === 50) &&
    !(srcFps === 30 && spec.fps === 60);

  const saveName = async () => {
    const normalized = nameDraft.trim().replace(/\s+/g, " ");
    if (!normalized) {
      setNameError("Inserisci un nome per il progetto.");
      return;
    }
    if (normalized.length > 120) {
      setNameError("Il nome può contenere al massimo 120 caratteri.");
      return;
    }
    if (normalized === projectName) {
      setNameError(null);
      return;
    }
    setNameBusy(true);
    setNameError(null);
    try {
      const updated = await updateProject(projectId, { name: normalized });
      setProjectName(updated.name);
      setNameDraft(updated.name);
    } catch (err) {
      setNameError(err instanceof Error ? err.message : "Impossibile salvare il nome");
    } finally {
      setNameBusy(false);
    }
  };

  return (
    <section aria-label="Impostazioni progetto e output" className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
      <div className="mb-5 border-b border-slate-800 pb-5">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Progetto</h3>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs text-slate-400">
            Titolo del progetto
            <input
              value={nameDraft}
              onChange={e => setNameDraft(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") void saveName(); }}
              maxLength={120}
              disabled={nameBusy}
              placeholder="Es. Vacanze in Andalusia"
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-violet-400/60 focus:ring-2 focus:ring-violet-400/10 disabled:opacity-50"
              aria-label="Titolo del progetto"
            />
          </label>
          <button
            type="button"
            onClick={() => void saveName()}
            disabled={nameBusy || !nameDraft.trim()}
            className="rounded-lg bg-white px-3 py-2 text-sm font-semibold text-slate-950 transition hover:bg-violet-100 disabled:opacity-50"
          >
            {nameBusy ? "Salvataggio…" : "Salva titolo"}
          </button>
        </div>
        {nameError && <p className="mt-2 text-xs text-rose-300">{nameError}</p>}
        <p className="mt-2 text-[11px] text-slate-500">Titolo attuale: {projectName}</p>
      </div>

      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">Output 16:9</h3>
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Sfondo verticali
          <select value={spec.background_fill} disabled={busy} onChange={e => void onSave({ background_fill: e.target.value as BackgroundFill })}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 disabled:opacity-50"
            title="Riempimento laterale per i media verticali (mai croppati)">
            <option value="blur">Blur</option>
            <option value="solid_color">Tinta unita</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Risoluzione
          <select value={RESOLUTIONS.includes(spec.resolution) ? spec.resolution : "1920x1080"} disabled={busy} onChange={e => void onSave({ resolution: e.target.value })}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 disabled:opacity-50">
            {RESOLUTIONS.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          FPS
          <select value={FPS_OPTIONS.includes(spec.fps) ? spec.fps : 30} disabled={busy} onChange={e => void onSave({ fps: Number(e.target.value) })}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 disabled:opacity-50">
            {FPS_OPTIONS.map(f => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Codec
          <select value={spec.vcodec ?? "h264"} disabled={busy} onChange={e => void onSave({ vcodec: e.target.value as "h264" | "h265" })}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 disabled:opacity-50"
            title="H.264 compatibile ovunque, H.265 file più leggeri">
            <option value="h264">H.264</option>
            <option value="h265">H.265</option>
          </select>
        </label>
        {busy && <span className="pb-2 text-xs text-slate-500">Salvataggio…</span>}
      </div>
      <p className="mt-2 text-[11px] text-slate-500">I verticali restano sempre interi e centrati; lo sfondo riempie solo i lati.</p>
      <p className="mt-1 text-[11px] text-slate-500" title="Convertire tra fps non multipli duplica qualche frame al secondo: si vede come micro-scatto sui movimenti.">
        FPS: 30 equilibrato · 60 Ken Burns più fluido · video europei (25fps) → 25 o 50.
      </p>
      {mismatch && (
        <p className="mt-1 text-[11px] text-amber-300">
          I tuoi video sono a {srcFps}fps ma l&apos;output è a {spec.fps}fps: potresti vedere micro-scatti.
          Prova {srcFps === 25 ? "25 o 50" : srcFps === 30 ? "30 o 60" : `${srcFps}`}fps.
        </p>
      )}
    </section>
  );
}
