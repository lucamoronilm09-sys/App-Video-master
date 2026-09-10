"use client";

import { useEffect, useState } from "react";
import { CLIP_MOVEMENTS, type ClipOverride, type EditEntry, type MediaItem, type ProjectState } from "@/lib/api";

interface MontageSectionProps {
  project: ProjectState;
  onGenerate: () => Promise<void>;
  onPatchClip: (mediaId: string, patch: ClipOverride) => Promise<void>;
  onResetClip: (mediaId: string) => Promise<void>;
  busy?: boolean;
}

const MOVEMENT_LABEL: Record<string, string> = {
  pan_left: "Pan ←",
  pan_right: "Pan →",
  zoom_in_slow: "Zoom +",
  zoom_out_slow: "Zoom −",
  pan_and_zoom_diag: "Diag",
  static: "Fermo",
  auto: "Auto",
};

interface ClipRowProps {
  entry: EditEntry;
  index: number;
  isLast: boolean;
  media?: MediaItem;
  overridden: boolean;
  disabled: boolean;
  onPatch: (mediaId: string, patch: ClipOverride) => Promise<void>;
  onReset: (mediaId: string) => Promise<void>;
}

function ClipRow({ entry, index, isLast, media, overridden, disabled, onPatch, onReset }: ClipRowProps) {
  const isPhoto = (media?.type ?? (entry.ken_burns ? "photo" : "video")) === "photo";
  const durMin = isPhoto ? 3.0 : 0.5;
  const durMax = isPhoto ? 8.0 : Math.max(0.5, media?.duration_sec ?? 8.0);
  const [durText, setDurText] = useState(entry.duration_sec.toFixed(1));
  const [trans, setTrans] = useState(entry.transition_out);
  const [rowError, setRowError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDurText(entry.duration_sec.toFixed(1));
    setTrans(entry.transition_out);
  }, [entry.duration_sec, entry.transition_out]);

  const save = async (patch: ClipOverride) => {
    setRowError(null);
    setSaving(true);
    try {
      await onPatch(entry.media_id, patch);
    } catch (err) {
      setRowError(err instanceof Error ? err.message : "Salvataggio fallito");
    } finally {
      setSaving(false);
    }
  };

  const commitDuration = () => {
    const v = Number(durText.replace(",", "."));
    if (!Number.isFinite(v)) {
      setDurText(entry.duration_sec.toFixed(1));
      return;
    }
    if (Math.abs(v - entry.duration_sec) < 0.005) {
      setDurText(entry.duration_sec.toFixed(1));
      return;
    }
    void save({ duration_sec: Math.round(v * 100) / 100 });
  };

  const commitTransition = (v: number) => {
    if (Math.abs(v - entry.transition_out) < 0.001) return;
    void save({ transition_out: Math.round(v * 100) / 100 });
  };

  return (
    <li className="rounded-lg bg-slate-800/70 px-2.5 py-1.5">
      <div className="flex items-center gap-2 text-xs text-slate-300">
        <span className="font-bold text-slate-400">#{index + 1}</span>
        <span className="tabular-nums text-slate-500">⏱ {entry.start_sec_in_final_video.toFixed(1)}s</span>
        <label className="flex items-center gap-1 tabular-nums" title={isPhoto ? "Durata foto (3–8s)" : `Durata video (0.5–${durMax.toFixed(1)}s, ricentra il taglio)`}>
          <input
            type="number"
            value={durText}
            min={durMin}
            max={durMax}
            step={0.1}
            disabled={disabled || saving}
            onChange={e => setDurText(e.target.value)}
            onBlur={commitDuration}
            onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
            className="w-14 rounded border border-slate-600 bg-slate-900 px-1 py-0.5 text-right tabular-nums disabled:opacity-50"
            aria-label={`Durata clip ${index + 1} in secondi`}
          />
          s
        </label>
        {isPhoto ? (
          <select
            defaultValue={entry.ken_burns?.movement ?? "auto"}
            key={`${entry.media_id}:${entry.ken_burns?.movement ?? "auto"}`}
            disabled={disabled || saving}
            onChange={e => void save({ ken_burns_movement: e.target.value })}
            className="rounded border border-slate-600 bg-slate-900 px-1 py-0.5 text-xs disabled:opacity-50"
            aria-label={`Movimento clip ${index + 1}`}
            title="Movimento Ken Burns (Auto = scelta del regista)"
          >
            <option value="auto">Auto{entry.ken_burns ? `: ${MOVEMENT_LABEL[entry.ken_burns.movement] ?? entry.ken_burns.movement}` : ""}</option>
            {CLIP_MOVEMENTS.map(m => (
              <option key={m.value} value={m.value}>{MOVEMENT_LABEL[m.value] ?? m.label}</option>
            ))}
          </select>
        ) : (
          <span className="text-slate-500">▶ video</span>
        )}
        <span className="flex-1" />
        {overridden && (
          <span className="rounded bg-sky-900/60 px-1.5 py-0.5 text-[10px] font-medium text-sky-300" title="Hai modificato questa clip a mano">
            manuale
          </span>
        )}
        {overridden && (
          <button
            type="button"
            disabled={disabled || saving}
            onClick={() => {
              setRowError(null);
              setSaving(true);
              onReset(entry.media_id)
                .catch(err => setRowError(err instanceof Error ? err.message : "Reset fallito"))
                .finally(() => setSaving(false));
            }}
            className="text-slate-500 hover:text-slate-200 disabled:opacity-50"
            title="Togli le modifiche manuali (torna al regista)"
            aria-label={`Reset modifiche clip ${index + 1}`}
          >
            ⟲
          </button>
        )}
        {saving && <span className="text-[10px] text-slate-500">…</span>}
      </div>
      {!isLast && (
        <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
          <span className="shrink-0" title="Dissolvenza verso la clip successiva (0 = stacco secco)">⋈</span>
          <input
            type="range"
            min={0}
            max={1.5}
            step={0.05}
            value={trans}
            disabled={disabled || saving}
            onChange={e => setTrans(Number(e.target.value))}
            onMouseUp={() => commitTransition(trans)}
            onTouchEnd={() => commitTransition(trans)}
            onKeyUp={() => commitTransition(trans)}
            className="h-1 flex-1 accent-sky-500 disabled:opacity-50"
            aria-label={`Transizione dopo la clip ${index + 1} in secondi`}
          />
          <span className="w-16 shrink-0 tabular-nums">
            {trans === 0 ? "stacco" : `${trans.toFixed(2)}s`}
          </span>
        </div>
      )}
      {rowError && <p className="mt-1 text-[11px] text-rose-300">{rowError}</p>}
    </li>
  );
}

export function MontageSection({ project, onGenerate, onPatchClip, onResetClip, busy }: MontageSectionProps) {
  const [error, setError] = useState<string | null>(null);
  const edl = project.edit_decision_list ?? [];
  const overrides = project.clip_overrides ?? {};
  const manifest = project.render_manifest;
  const mediaById = new Map(project.media.map(m => [m.id, m]));

  const handleClick = async () => {
    setError(null);
    try {
      await onGenerate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generazione montaggio fallita");
    }
  };

  return (
    <section aria-label="Piano di montaggio" className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Montaggio</h3>
        <button
          type="button"
          disabled={busy || project.media.length === 0}
          onClick={handleClick}
          className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
        >
          {busy ? "Generazione…" : edl.length ? "↻ Rigenera montaggio" : "✨ Genera montaggio"}
        </button>
      </div>

      {error && <p className="mb-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">{error}</p>}

      {edl.length === 0 && !error && <p className="text-sm text-slate-500">Il regista IA deciderà Ken Burns, dissolvenze e sincronizzazione sulla musica.</p>}

      {edl.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            {edl.length} clip · totale <strong>{manifest?.total_sec ? manifest.total_sec.toFixed(1) : "…"}s</strong>
            {manifest?.audio ? " · con audio" : " · senza audio"}
          </p>
          <ol className="space-y-1">
            {edl.map((e, i) => (
              <ClipRow key={e.media_id} entry={e} index={i} isLast={i === edl.length - 1} media={mediaById.get(e.media_id)} overridden={!!overrides[e.media_id]} disabled={!!busy} onPatch={onPatchClip} onReset={onResetClip} />
            ))}
          </ol>
          <p className="text-[11px] leading-relaxed text-slate-500">
            ✏️ Tocca durata, dissolvenza (0 = stacco) o movimento per ritoccare ogni clip.
            Le foto vengono valutate automaticamente tra 3 e 8 secondi; le clip <span className="text-sky-300">manuali</span> restano bloccate anche dopo “Rigenera”. Dopo ogni modifica riesporta il video per vederla nel risultato.
          </p>
        </div>
      )}
    </section>
  );
}
