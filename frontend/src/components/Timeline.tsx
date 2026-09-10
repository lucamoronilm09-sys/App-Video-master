"use client";

import { useMemo, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { mediaThumbUrl, type BackgroundFill, type MediaItem } from "@/lib/api";

interface TimelineProps {
  projectId: string;
  media: MediaItem[];
  onReorder: (mediaIds: string[]) => Promise<void>;
  onToggleFill: (mediaId: string, fill: BackgroundFill) => Promise<void>;
  onDelete: (mediaId: string) => Promise<void>;
  onReplace: (mediaId: string, file: File) => Promise<void>;
  busy?: boolean;
}

function DurationBadge({ m }: { m: MediaItem }) {
  if (m.type === "photo") return <span>{m.duration_sec > 0 ? `${m.duration_sec.toFixed(1)}s` : "foto"}</span>;
  if (m.trim_start_sec != null && m.trim_end_sec != null) {
    const eff = m.trim_end_sec - m.trim_start_sec;
    return <span title={`Originale ${m.duration_sec.toFixed(1)}s — trim ${m.trim_start_sec.toFixed(1)}–${m.trim_end_sec.toFixed(1)}s`}>✂ {eff.toFixed(1)}s</span>;
  }
  return <span>{m.duration_sec.toFixed(1)}s</span>;
}

function SourceFpsBadge({ m }: { m: MediaItem }) {
  if (m.type !== "video" || typeof m.source_fps !== "number") return null;
  return <div className="flex items-center gap-1"><span className="rounded bg-slate-700 px-1 py-0.5 text-[10px] text-slate-300" title={`Frame rate nativo: ${m.source_fps}fps`}>{m.source_fps}fps</span></div>;
}

const ACCEPT_MEDIA = "image/*,video/*,.heic,.heif";

export function Timeline({ projectId, media, onReorder, onToggleFill, onDelete, onReplace, busy }: TimelineProps) {
  const sorted = useMemo(() => [...media].sort((a, b) => a.order_index - b.order_index), [media]);
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [replacingId, setReplacingId] = useState<string | null>(null);
  const dragRef = useRef<string | null>(null);
  const replaceInputRef = useRef<HTMLInputElement | null>(null);
  const replaceTargetRef = useRef<string | null>(null);
  const [touchDragId, setTouchDragId] = useState<string | null>(null);
  const [touchDragIndex, setTouchDragIndex] = useState<number>(-1);
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const touchStartX = useRef<number>(0);

  if (sorted.length === 0) return null;

  const move = async (fromId: string, toId: string) => {
    if (fromId === toId || busy) return;
    const ids = sorted.map(m => m.id).filter(id => id !== fromId);
    const targetIdx = ids.indexOf(toId);
    ids.splice(targetIdx < 0 ? ids.length : targetIdx, 0, fromId);
    setError(null);
    try { await onReorder(ids); }
    catch (err) { setError(err instanceof Error ? err.message : "Riordino fallito"); }
  };

  const shift = async (id: string, dir: -1 | 1) => {
    const idx = sorted.findIndex(m => m.id === id);
    const j = idx + dir;
    if (idx < 0 || j < 0 || j >= sorted.length || busy) return;
    const ids = sorted.map(m => m.id);
    [ids[idx], ids[j]] = [ids[j], ids[idx]];
    setError(null);
    try { await onReorder(ids); }
    catch (err) { setError(err instanceof Error ? err.message : "Riordino fallito"); }
  };

  const handleDelete = async (m: MediaItem) => {
    if (deletingId || replacingId || busy) return;
    const label = m.type === "photo" ? "foto" : "video";
    if (!window.confirm(`Eliminare definitivamente questo ${label} dal progetto?\n\nIl montaggio corrente dovrà essere rigenerato.`)) return;
    setError(null); setDeletingId(m.id);
    try { await onDelete(m.id); }
    catch (err) { setError(err instanceof Error ? err.message : "Eliminazione fallita"); }
    finally { setDeletingId(null); }
  };

  const openReplace = (id: string) => {
    if (busy || deletingId || replacingId) return;
    replaceTargetRef.current = id;
    replaceInputRef.current?.click();
  };

  const handleReplaceChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    const id = replaceTargetRef.current;
    e.target.value = "";
    replaceTargetRef.current = null;
    if (!file || !id) return;
    setError(null); setReplacingId(id);
    try { await onReplace(id, file); }
    catch (err) { setError(err instanceof Error ? err.message : "Sostituzione fallita"); }
    finally { setReplacingId(null); }
  };

  const handleDragStart = (e: DragEvent, id: string) => {
    dragRef.current = id; setDragId(id); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", id);
  };
  const handleDragOver = (e: DragEvent, id: string) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; if (id !== dragRef.current) setOverId(id); };
  const handleDrop = async (e: DragEvent, id: string) => {
    e.preventDefault();
    const fromId = dragRef.current ?? e.dataTransfer.getData("text/plain");
    setOverId(null); setDragId(null); dragRef.current = null;
    if (fromId) await move(fromId, id);
  };
  const handleDragEnd = () => { setDragId(null); setOverId(null); dragRef.current = null; };

  const handleTouchStart = (e: React.TouchEvent, id: string, index: number) => {
    longPressTimer.current = setTimeout(() => {
      setTouchDragId(id); setTouchDragIndex(index); touchStartX.current = e.touches[0].clientX;
      if (navigator.vibrate) navigator.vibrate(50);
    }, 500);
  };
  const handleTouchMove = (e: React.TouchEvent) => {
    if (!touchDragId || touchDragIndex === -1 || busy) return;
    e.preventDefault();
    const currentX = e.touches[0].clientX;
    const deltaX = currentX - touchStartX.current;
    if (Math.abs(deltaX) > 80) {
      const direction = deltaX > 0 ? 1 : -1;
      const newIndex = touchDragIndex + direction;
      if (newIndex >= 0 && newIndex < sorted.length) {
        const ids = sorted.map(c => c.id);
        [ids[touchDragIndex], ids[newIndex]] = [ids[newIndex], ids[touchDragIndex]];
        void onReorder(ids);
        setTouchDragIndex(newIndex); touchStartX.current = currentX;
        if (navigator.vibrate) navigator.vibrate(10);
      }
    }
  };
  const handleTouchEnd = () => {
    if (longPressTimer.current) { clearTimeout(longPressTimer.current); longPressTimer.current = null; }
    if (touchDragId !== null) { if (navigator.vibrate) navigator.vibrate(50); setTouchDragId(null); setTouchDragIndex(-1); }
  };

  return (
    <div className="mt-8">
      <input ref={replaceInputRef} type="file" accept={ACCEPT_MEDIA} className="hidden" onChange={handleReplaceChange} />
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Timeline ({sorted.length})</h3>
        <p className="text-xs text-slate-500">Trascina le clip per cambiare posizione · sostituisci i contenuti</p>
      </div>
      {error && <p className="mb-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">{error}</p>}
      <ol className={`flex gap-3 overflow-x-auto pb-3 ${busy || deletingId || replacingId ? "pointer-events-none opacity-60" : ""}`} aria-label="Timeline clip">
        {sorted.map((m, i) => {
          const isDragged = dragId === m.id;
          const isOver = overId === m.id;
          const isTouchDragging = touchDragId === m.id;
          const isDeleting = deletingId === m.id;
          const isReplacing = replacingId === m.id;
          return (
            <li key={m.id} draggable={!busy && !deletingId && !replacingId && !isTouchDragging} onDragStart={e => handleDragStart(e, m.id)} onDragOver={e => handleDragOver(e, m.id)} onDrop={e => void handleDrop(e, m.id)} onDragEnd={handleDragEnd} onTouchStart={e => handleTouchStart(e, m.id, i)} onTouchMove={handleTouchMove} onTouchEnd={handleTouchEnd} aria-label={`Clip ${i + 1} di ${sorted.length}. Trascina per cambiare posizione`} className={`relative w-44 shrink-0 overflow-hidden rounded-lg border bg-black ${isOver ? "border-emerald-400 ring-2 ring-emerald-400/50" : "border-slate-700"} ${isDragged ? "opacity-40" : ""} ${busy ? "" : "cursor-grab active:cursor-grabbing"} ${isTouchDragging ? "scale-110 shadow-2xl opacity-80 z-20 bg-gray-800" : ""}`}>
              <span className="absolute left-1.5 top-1.5 z-10 rounded bg-black/70 px-1.5 py-0.5 text-xs font-bold text-white">{i + 1}</span>
              <div className="aspect-video w-full bg-slate-900">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={mediaThumbUrl(projectId, m.id)} alt={m.type === "photo" ? "Anteprima foto" : "Fotogramma anteprima video"} draggable={false} loading="lazy" className={`h-full w-full ${m.fit_mode === "contain" ? "object-contain" : "object-cover"}`} />
              </div>
              {m.type === "video" && <span className="absolute right-1.5 top-1.5 z-10 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-white" title="Video senza audio nel render">VIDEO</span>}
              {isReplacing && <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/70 text-xs text-white">Sostituzione…</div>}

              <div className="space-y-1 bg-slate-800/90 p-2 text-[11px] leading-tight text-slate-300">
                <div className="flex items-center justify-between gap-1"><span className="truncate">{m.orientation}</span><DurationBadge m={m} /></div>
                <SourceFpsBadge m={m} />
                <div className="flex items-center gap-1">
                  <span className={`rounded px-1 py-0.5 text-[10px] font-medium ${m.fit_mode === "contain" ? "bg-sky-900/60 text-sky-300" : "bg-slate-700 text-slate-300"}`}>{m.fit_mode ?? "…"}</span>
                  {m.fit_mode === "contain" && <button type="button" disabled={busy || !!deletingId || !!replacingId} onClick={() => void onToggleFill(m.id, m.background_fill === "blur" ? "solid_color" : "blur")} className="rounded bg-slate-700 px-1 py-0.5 text-[10px] text-slate-300 hover:bg-slate-600 disabled:opacity-50">{m.background_fill === "solid_color" ? "tinta" : "blur"}</button>}
                </div>
                <div className="flex items-center justify-between pt-0.5">
                  <button type="button" disabled={busy || !!deletingId || !!replacingId || i === 0} onClick={() => void shift(m.id, -1)} aria-label={`Sposta clip ${i + 1} a sinistra`} className="rounded px-1.5 py-0.5 text-slate-400 hover:bg-slate-700 hover:text-white disabled:opacity-30">◀</button>
                  <button type="button" disabled={busy || !!deletingId || !!replacingId || i === sorted.length - 1} onClick={() => void shift(m.id, 1)} aria-label={`Sposta clip ${i + 1} a destra`} className="rounded px-1.5 py-0.5 text-slate-400 hover:bg-slate-700 hover:text-white disabled:opacity-30">▶</button>
                  <button type="button" disabled={busy || !!deletingId || !!replacingId} onClick={() => openReplace(m.id)} aria-label={`Sostituisci ${m.type} ${i + 1}`} title="Sostituisci foto/video mantenendo la posizione" className="rounded px-1.5 py-0.5 text-sky-300 hover:bg-sky-500/10 disabled:opacity-30">↻</button>
                  <button type="button" disabled={busy || !!deletingId || !!replacingId} onClick={() => void handleDelete(m)} aria-label={`Elimina clip ${i + 1}`} title="Elimina caricamento" className="rounded px-1.5 py-0.5 text-rose-400 hover:bg-rose-500/10 disabled:opacity-30">{isDeleting ? "…" : "🗑"}</button>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
