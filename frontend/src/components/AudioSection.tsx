"use client";

import { useRef, useState, type ChangeEvent } from "react";
import type { AudioInfo, AudioTrack } from "@/lib/api";

interface AudioSectionProps {
  audio?: AudioInfo;
  tracks?: AudioTrack[];
  onUpload: (file: File) => Promise<void>;
  busy?: boolean;
}

export function AudioSection({ audio, tracks = [], onUpload, busy }: AudioSectionProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const visibleTracks = tracks.length ? tracks : (audio?.path ? [audio] : []);

  const handleSelect = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (!files.length) return;
    setError(null);
    try {
      for (const file of files) {
        await onUpload(file);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload audio fallito");
    }
  };

  return (
    <section aria-label="Tracce audio" className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Audio</h3>
          <p className="mt-1 text-xs text-slate-500">Puoi aggiungere più brani: vengono riprodotti uno dopo l&apos;altro e la playlist si ripete se il video è più lungo.</p>
        </div>
        <button type="button" disabled={busy} onClick={() => inputRef.current?.click()}
          className="text-xs text-emerald-400 hover:underline disabled:opacity-50">
          {busy ? "Analisi…" : visibleTracks.length ? "Aggiungi tracce" : "Carica musica"}
        </button>
      </div>

      <input ref={inputRef} type="file" accept="audio/*" multiple onChange={handleSelect} className="hidden" disabled={busy} aria-label="Seleziona file audio da caricare" />

      {!visibleTracks.length ? (
        <button type="button" disabled={busy} onClick={() => inputRef.current?.click()}
          className="w-full rounded-lg border-2 border-dashed border-slate-700 p-6 text-center text-slate-300 hover:border-slate-500 disabled:opacity-50">
          {busy ? "Analisi in corso…" : "🎵 Carica una o più tracce (MP3, WAV, OGG, M4A…)"}
        </button>
      ) : (
        <div className="space-y-2">
          {visibleTracks.map((track, index) => (
            <div key={track.id ?? track.path ?? index} className="flex items-center justify-between rounded-lg bg-slate-800/70 px-3 py-2 text-sm text-slate-300">
              <span className="min-w-0 truncate">#{index + 1} · {track.name ?? track.path?.split(/[/\\]/).pop() ?? "traccia"}</span>
              <span className="ml-3 shrink-0 text-xs text-slate-500">{track.duration_sec.toFixed(1)}s</span>
            </div>
          ))}
          <p className="text-xs text-slate-500">Durata playlist: {visibleTracks.reduce((s, t) => s + (t.duration_sec || 0), 0).toFixed(1)}s</p>
        </div>
      )}

      {error && <p className="mt-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">{error}</p>}
    </section>
  );
}
