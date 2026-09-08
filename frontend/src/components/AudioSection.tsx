"use client";

import { useRef, useState, type ChangeEvent } from "react";
import type { AudioInfo } from "@/lib/api";

interface AudioSectionProps {
  audio: AudioInfo;
  onUpload: (file: File) => Promise<void>;
  busy?: boolean;
}

/** M3: upload traccia utente + riepilogo analisi (durata, bpm, marker, energia). */
export function AudioSection({ audio, onUpload, busy }: AudioSectionProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSelect = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError(null);
    try {
      await onUpload(file);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload audio fallito");
    }
  };

  const fileName = audio.path ? audio.path.split(/[/\\]/).pop() : null;
  const hasAudio = !!audio.path;

  return (
    <section aria-label="Traccia audio" className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
          Audio
        </h3>
        {hasAudio && (
          <button
            type="button"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
            className="text-xs text-emerald-400 hover:underline disabled:opacity-50"
          >
            {busy ? "Analisi in corso…" : "Sostituisci traccia"}
          </button>
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="audio/*"
        onChange={handleSelect}
        className="hidden"
        disabled={busy}
      />

      {!hasAudio ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
          className="w-full rounded-lg border-2 border-dashed border-slate-700 p-6 text-center text-slate-300 transition-colors hover:border-slate-500 disabled:opacity-50"
        >
          {busy ? "Analisi in corso…" : "🎵 Carica la traccia audio (MP3, WAV, OGG, M4A…)"}
        </button>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-300">
            <span className="truncate" title={audio.path ?? ""}>🎵 {fileName}</span>
            <span>{audio.duration_sec.toFixed(1)}s</span>
            <span title="Battiti per minuto stimati">
              {audio.bpm > 0 ? `${audio.bpm.toFixed(0)} BPM` : "BPM non rilevato"}
            </span>
            <span title="Marker strutturali (uno per battuta) per la sincronizzazione">
              {audio.beat_markers_sec.length} marker
            </span>
          </div>
          {audio.energy_curve.length > 0 && (
            <div
              className="flex h-10 items-end gap-[2px]"
              aria-label="Curva di energia"
              title="Energia del brano (1 barra = 1 secondo)"
            >
              {audio.energy_curve.map((v, i) => (
                <div
                  key={i}
                  className="min-w-[3px] flex-1 rounded-sm bg-emerald-500/70"
                  style={{ height: `${Math.max(4, Math.round(v * 100))}%` }}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {error && (
        <p className="mt-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">
          {error}
        </p>
      )}
    </section>
  );
}
