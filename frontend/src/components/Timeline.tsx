"use client";

import { useMemo, useRef, useState, type DragEvent } from "react";
import { mediaThumbUrl, type BackgroundFill, type MediaItem } from "@/lib/api";

interface TimelineProps {
  projectId: string;
  media: MediaItem[];
  onReorder: (mediaIds: string[]) => Promise<void>;
  onToggleFill: (mediaId: string, fill: BackgroundFill) => Promise<void>;
  onDelete: (mediaId: string) => Promise<void>;
  busy?: boolean;
}

/** Durata effettiva: foto = durata assegnata; video = trim centrale se presente. */
function DurationBadge({ m }: { m: MediaItem }) {
  if (m.type === "photo") {
    return <span>{m.duration_sec > 0 ? `${m.duration_sec.toFixed(1)}s` : "foto"}</span>;
  }
  if (m.trim_start_sec != null && m.trim_end_sec != null) {
    const eff = m.trim_end_sec - m.trim_start_sec;
    return (
      <span title={`Originale ${m.duration_sec.toFixed(1)}s — trim centrale ${m.trim_start_sec.toFixed(1)}–${m.trim_end_sec.toFixed(1)}s`}>
        ✂ {eff.toFixed(1)}s
      </span>
    );
  }
  return <span>{m.duration_sec.toFixed(1)}s</span>;
}

/** fps nativo del video (se rilevato): aiuta a scegliere un fps di output senza scatti. */
function SourceFpsBadge({ m }: { m: MediaItem }) {
  if (m.type !== "video" || typeof m.source_fps !== "number") return null;
  return (
    <div className="flex items-center gap-1">
      <span
        className="rounded bg-slate-700 px-1 py-0.5 text-[10px] text-slate-300"
        title={`Frame rate nativo: ${m.source_fps}fps — per movimenti fluidi usa lo stesso fps (o un suo multiplo) nelle impostazioni output`}
      >
        {m.source_fps}fps
      </span>
    </div>
  );
}

/** Striscia orizzontale ordinabile: l'ordine visivo = order_index (RF2).
 * Drag&drop nativo HTML5 + frecce ◀ ▶ come fallback (mobile/tastiera).
 * Touch support: long-press (500ms) + swipe per riordinare su mobile. */
export function Timeline({ projectId, media, onReorder, onToggleFill, onDelete, busy }: TimelineProps) {
  const sorted = useMemo(
    () => [...media].sort((a, b) => a.order_index - b.order_index),
    [media],
  );
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const dragRef = useRef<string | null>(null);
  
  // Touch reordering states
  const [touchDragId, setTouchDragId] = useState<string | null>(null);
  const [touchDragIndex, setTouchDragIndex] = useState<number>(-1);
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const touchStartX = useRef<number>(0);

  if (sorted.length === 0) return null;

  const move = async (fromId: string, toId: string) => {
    if (fromId === toId) return;
    const ids = sorted.map(m => m.id).filter(id => id !== fromId);
    const targetIdx = ids.indexOf(toId);
    ids.splice(targetIdx < 0 ? ids.length : targetIdx, 0, fromId);
    setError(null);
    try {
      await onReorder(ids);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Riordino fallito");
    }
  };

  const shift = async (id: string, dir: -1 | 1) => {
    const idx = sorted.findIndex(m => m.id === id);
    const j = idx + dir;
    if (idx < 0 || j < 0 || j >= sorted.length) return;
    const ids = sorted.map(m => m.id);
    [ids[idx], ids[j]] = [ids[j], ids[idx]];
    setError(null);
    try {
      await onReorder(ids);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Riordino fallito");
    }
  };

  const handleDelete = async (m: MediaItem) => {
    if (deletingId || busy) return;
    const label = m.type === "photo" ? "foto" : "video";
    const confirmed = window.confirm(`Eliminare definitivamente questo ${label} dal progetto?\n\nIl file verrà rimosso e il montaggio corrente dovrà essere rigenerato.`);
    if (!confirmed) return;
    setError(null);
    setDeletingId(m.id);
    try {
      await onDelete(m.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Eliminazione fallita");
    } finally {
      setDeletingId(null);
    }
  };

  const handleDragStart = (e: DragEvent, id: string) => {
    dragRef.current = id;
    setDragId(id);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", id);
  };

  const handleDragOver = (e: DragEvent, id: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (id !== dragRef.current) setOverId(id);
  };

  const handleDrop = async (e: DragEvent, id: string) => {
    e.preventDefault();
    const fromId = dragRef.current ?? e.dataTransfer.getData("text/plain");
    setOverId(null);
    setDragId(null);
    dragRef.current = null;
    if (fromId) await move(fromId, id);
  };

  const handleDragEnd = () => {
    setDragId(null);
    setOverId(null);
    dragRef.current = null;
  };

  // Touch handlers for mobile-friendly reordering
  const handleTouchStart = (e: React.TouchEvent, id: string, index: number) => {
    longPressTimer.current = setTimeout(() => {
      setTouchDragId(id);
      setTouchDragIndex(index);
      touchStartX.current = e.touches[0].clientX;
      if (typeof navigator !== "undefined" && navigator.vibrate) navigator.vibrate(50);
    }, 500);
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    if (!touchDragId || touchDragIndex === -1) return;
    e.preventDefault();
    const currentX = e.touches[0].clientX;
    const deltaX = currentX - touchStartX.current;
    const threshold = 80;
    if (Math.abs(deltaX) > threshold) {
      const direction = deltaX > 0 ? 1 : -1;
      const newIndex = touchDragIndex + direction;
      if (newIndex >= 0 && newIndex < sorted.length) {
        const newClips = [...sorted];
        [newClips[touchDragIndex], newClips[newIndex]] = [newClips[newIndex], newClips[touchDragIndex]];
        void onReorder(newClips.map(c => c.id));
        setTouchDragIndex(newIndex);
        touchStartX.current = currentX;
        if (typeof navigator !== "undefined" && navigator.vibrate) navigator.vibrate(10);
      }
    }
  };

  const handleTouchEnd = () => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
    if (touchDragId !== null) {
      if (typeof navigator !== "undefined" && navigator.vibrate) navigator.vibrate(50);
      setTouchDragId(null);
      setTouchDragIndex(-1);
    }
  };

  return (
    <div className="mt-8">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
          Timeline ({sorted.length})
        </h3>
        <p className="text-xs text-slate-500">Trascina le clip per riordinare</p>
      </div>

      {error && (
        <p className="mb-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">
          {error}
        </p>
      )}

      <ol
        className={`flex gap-3 overflow-x-auto pb-3 ${busy || deletingId ? "pointer-events-none opacity-60" : ""}`}
        aria-label="Timeline clip"
      >
        {sorted.map((m, i) => {
          const isDragged = dragId === m.id;
          const isOver = overId === m.id;
          const isTouchDragging = touchDragId === m.id;
          const isDeleting = deletingId === m.id;
          return (
            <li
              key={m.id}
              draggable={!busy && !deletingId && !isTouchDragging}
              onDragStart={e => handleDragStart(e, m.id)}
              onDragOver={e => handleDragOver(e, m.id)}
              onDrop={e => void handleDrop(e, m.id)}
              onDragEnd={handleDragEnd}
              onTouchStart={e => handleTouchStart(e, m.id, i)}
              onTouchMove={handleTouchMove}
              onTouchEnd={handleTouchEnd}
              aria-label={`Clip ${i + 1} di ${sorted.length}. ${isTouchDragging ? 'Riordinamento attivo' : 'Premi a lungo per riordinare su mobile'}`}
              className={`
                relative w-44 shrink-0 overflow-hidden rounded-lg border bg-black
                ${isOver ? "border-emerald-400 ring-2 ring-emerald-400/50" : "border-slate-700"}
                ${isDragged ? "opacity-40" : ""}
                ${busy ? "" : "cursor-grab active:cursor-grabbing"}
                ${isTouchDragging ? " scale-110 shadow-2xl opacity-80 z-20 bg-gray-800" : ""}
              `}
            >
              <span className="absolute left-1.5 top-1.5 z-10 rounded bg-black/70 px-1.5 py-0.5 text-xs font-bold text-white">
                {i + 1}
              </span>

              <div className="aspect-video w-full bg-slate-900">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={mediaThumbUrl(projectId, m.id)}
                  alt=""
                  draggable={false}
                  loading="lazy"
                  className={`h-full w-full ${m.fit_mode === "contain" ? "object-contain" : "object-cover"}`}
                />
              </div>
              {m.type === "video" && (
                <span className="absolute right-1.5 top-1.5 z-10 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-white" title="Video (fotogramma anteprima)">
                  🎬
                </span>
              )}

              <div className="space-y-1 bg-slate-800/90 p-2 text-[11px] leading-tight text-slate-300">
                <div className="flex items-center justify-between gap-1">
                  <span className="truncate">{m.orientation}</span>
                  <DurationBadge m={m} />
                </div>
                <SourceFpsBadge m={m} />
                <div className="flex items-center gap-1">
                  <span
                    className={`rounded px-1 py-0.5 text-[10px] font-medium ${
                      m.fit_mode === "contain"
                        ? "bg-sky-900/60 text-sky-300"
                        : "bg-slate-700 text-slate-300"
                    }`}
                    title={m.fit_mode === "contain" ? "Verticale: mai croppata, centrata" : "Orizzontale: riempie il frame"}
                  >
                    {m.fit_mode ?? "…"}
                  </span>
                  {m.fit_mode === "contain" && (
                    <button
                      type="button"
                      disabled={busy || !!deletingId}
                      onClick={() => void onToggleFill(m.id, m.background_fill === "blur" ? "solid_color" : "blur")}
                      title="Sfondo laterale: blur o tinta unita"
                      className="rounded bg-slate-700 px-1 py-0.5 text-[10px] text-slate-300 hover:bg-slate-600 disabled:opacity-50"
                    >
                      {m.background_fill === "solid_color" ? "tinta" : "blur"}
                    </button>
                  )}
                </div>
                <div className="flex items-center justify-between pt-0.5">
                  <button
                    type="button"
                    disabled={busy || !!deletingId || i === 0}
                    onClick={() => void shift(m.id, -1)}
                    aria-label={`Sposta clip ${i + 1} a sinistra`}
                    className="rounded px-1.5 py-0.5 text-slate-400 hover:bg-slate-700 hover:text-white disabled:opacity-30"
                  >
                    ◀
                  </button>
                  <button
                    type="button"
                    disabled={busy || !!deletingId || i === sorted.length - 1}
                    onClick={() => void shift(m.id, 1)}
                    aria-label={`Sposta clip ${i + 1} a destra`}
                    className="rounded px-1.5 py-0.5 text-slate-400 hover:bg-slate-700 hover:text-white disabled:opacity-30"
                  >
                    ▶
                  </button>
                  <button
                    type="button"
                    disabled={busy || !!deletingId}
                    onClick={() => void handleDelete(m)}
                    aria-label={`Elimina clip ${i + 1}`}
                    title="Elimina caricamento"
                    className="rounded px-1.5 py-0.5 text-rose-400 hover:bg-rose-500/10 hover:text-rose-300 disabled:opacity-30"
                  >
                    {isDeleting ? "…" : "🗑"}
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
