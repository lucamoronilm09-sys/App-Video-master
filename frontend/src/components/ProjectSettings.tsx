"use client";

import type { BackgroundFill, MediaItem } from "@/lib/api";

export interface OutputSpec {
  resolution: string;
  fps: number;
  background_fill: BackgroundFill;
  vcodec: "h264" | "h265";
}

interface ProjectSettingsProps {
  spec: OutputSpec;
  onSave: (patch: { background_fill?: BackgroundFill; resolution?: string; fps?: number; vcodec?: "h264" | "h265" }) => Promise<void>;
  busy?: boolean;
  /** Media del progetto: serve a consigliare un fps senza conversioni a scatti. */
  media?: MediaItem[];
}

const RESOLUTIONS = ["1280x720", "1920x1080", "3840x2160"];
const FPS_OPTIONS = [23, 24, 25, 29, 30, 50, 59, 60];

/** fps nativo dominante tra i video (null se nessun video o fps eterogenei/sconosciuti). */
function dominantSourceFps(media: MediaItem[] | undefined): number | null {
  const rates = (media ?? [])
    .filter(m => m.type === "video" && typeof m.source_fps === "number")
    .map(m => m.source_fps as number);
  if (rates.length === 0) return null;
  const rounded = rates.map(r => Math.round(r));
  if (new Set(rounded).size !== 1) return null;
  return Math.round(rates.reduce((a, b) => a + b, 0) / rates.length);
}

/** Pannello M2: sfondo default per i verticali + risoluzione/fps di output. */
export function ProjectSettings({ spec, onSave, busy, media }: ProjectSettingsProps) {
  const srcFps = dominantSourceFps(media);
  const mismatch =
    srcFps !== null &&
    Math.abs(srcFps - spec.fps) > 1 &&
    // 25↔50 e 30↔60 sono multipli interi: conversione pulita, nessuno scatto
    !(srcFps === 25 && spec.fps === 50) &&
    !(srcFps === 30 && spec.fps === 60);

  return (
    <section aria-label="Impostazioni output" className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
        Output 16:9
      </h3>
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Sfondo verticali
          <select
            value={spec.background_fill}
            disabled={busy}
            onChange={e => void onSave({ background_fill: e.target.value as BackgroundFill })}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 disabled:opacity-50"
            title="Riempimento laterale per i media verticali (mai croppati)"
          >
            <option value="blur">Blur</option>
            <option value="solid_color">Tinta unita</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Risoluzione
          <select
            value={RESOLUTIONS.includes(spec.resolution) ? spec.resolution : "1920x1080"}
            disabled={busy}
            onChange={e => void onSave({ resolution: e.target.value })}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 disabled:opacity-50"
          >
            {RESOLUTIONS.map(r => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          FPS
          <select
            value={FPS_OPTIONS.includes(spec.fps) ? spec.fps : 30}
            disabled={busy}
            onChange={e => void onSave({ fps: Number(e.target.value) })}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 disabled:opacity-50"
          >
            {FPS_OPTIONS.map(f => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Codec
          <select
            value={spec.vcodec ?? "h264"}
            disabled={busy}
            onChange={e => void onSave({ vcodec: e.target.value as "h264" | "h265" })}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 disabled:opacity-50"
            title="H.264 compatibile ovunque, H.265 file più leggeri"
          >
            <option value="h264">H.264</option>
            <option value="h265">H.265</option>
          </select>
        </label>
        {busy && <span className="pb-2 text-xs text-slate-500">Salvataggio…</span>}
      </div>
      <p className="mt-2 text-[11px] text-slate-500">
        I verticali restano sempre interi e centrati; lo sfondo riempie solo i lati.
      </p>
      <p className="mt-1 text-[11px] text-slate-500" title="Convertire tra fps non multipli (es. video 25fps → output 30fps) duplica qualche frame al secondo: si vede come micro-scatto sui movimenti.">
        FPS: 30 equilibrato · 60 Ken Burns più fluido (file più pesante) · video europei (25fps) → 25 o 50.
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
