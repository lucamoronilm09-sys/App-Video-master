"use client";

import { useCallback, useEffect, useRef, useState, DragEvent, ChangeEvent } from "react";
import { uploadMedia } from "@/lib/api";

interface UploadZoneProps {
  projectId: string;
  onUploadComplete: (mediaCount: number) => void;
  disabled?: boolean;
}

function formatError(err: unknown, fallback = "Errore sconosciuto"): { title: string; detail: string; hint?: string } {
  const msg = err instanceof Error ? err.message : fallback;
  const m = msg.toLowerCase();
  if (
    m.includes("impossibile raggiungere il server") ||
    m.includes("connettersi al server") ||
    m.includes("network") ||
    m.includes("fetch")
  ) {
    return {
      title: "Server non raggiungibile",
      detail: "Impossibile comunicare con il backend.",
      hint: "Verifica che il server sia in esecuzione su http://127.0.0.1:8000 (oppure imposta NEXT_PUBLIC_API_URL in produzione) e che la connessione di rete funzioni.",
    };
  }
  if (m.includes("timeout") || m.includes("scaduta")) {
    return {
      title: "Caricamento troppo lento",
      detail: "La richiesta è andata in timeout.",
      hint: "I file sono molto grandi o la connessione è lenta. Prova con meno file per volta o riprova più tardi.",
    };
  }
  if (m.includes("401") || m.includes("autorizzazione")) {
    return {
      title: "Autorizzazione mancante",
      detail: msg,
      hint: "Ricarica la pagina o ripeti l'accesso se richiesto.",
    };
  }
  if (m.includes("404") || m.includes("non trovato") || m.includes("progetto non trovato")) {
    return {
      title: "Progetto non trovato",
      detail: msg,
      hint: "Torna alla home e apri un progetto valido.",
    };
  }
  if (m.includes("413") || m.includes("troppo grande")) {
    return {
      title: "File troppo grande",
      detail: msg,
      hint: "Il limite è 500MB per file. Riduci le dimensioni o usa file più piccoli.",
    };
  }
  if (m.includes("estensione") || m.includes("non supportato") || m.includes("formato")) {
    return {
      title: "Formato non supportato",
      detail: msg,
      hint: "Formati consentiti: JPG, PNG, WebP, HEIC, MP4, MOV, MKV, WebM (e tutti i formati video/immagine comuni).",
    };
  }
  if (m.includes("400") || m.includes("non valido")) {
    return { title: "Richiesta non valida", detail: msg };
  }
  if (m.includes("500") || m.includes("interno")) {
    return {
      title: "Errore sul server",
      detail: msg,
      hint: "Riprova tra qualche istante. Se il problema persiste, controlla i log del backend.",
    };
  }
  return { title: "Errore durante il caricamento", detail: msg };
}

export function UploadZone({ projectId, onUploadComplete, disabled }: UploadZoneProps) {
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<{ title: string; detail: string; hint?: string } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const progressRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (progressRef.current) clearInterval(progressRef.current);
    };
  }, []);

  const uploadFiles = useCallback(async (files: File[]) => {
    setUploading(true);
    setProgress(0);
    setError(null);

    if (progressRef.current) clearInterval(progressRef.current);
    progressRef.current = setInterval(() => {
      setProgress(p => {
        if (p >= 90) return 90;
        const step = p < 30 ? 4 : p < 60 ? 2 : 1;
        return Math.min(90, p + step);
      });
    }, 200);

    try {
      const data = await uploadMedia(projectId, files);
      if (progressRef.current) {
        clearInterval(progressRef.current);
        progressRef.current = null;
      }
      setProgress(100);
      onUploadComplete(data.media.length);
    } catch (err) {
      if (progressRef.current) {
        clearInterval(progressRef.current);
        progressRef.current = null;
      }
      setError(formatError(err));
    } finally {
      setTimeout(() => {
        setUploading(false);
        setProgress(0);
      }, 600);
    }
  }, [projectId, onUploadComplete]);

  const handleDrag = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) setDragActive(e.type === "dragenter" || e.type === "dragover");
  }, [disabled]);

  const handleDrop = useCallback(async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (disabled) return;
    const files = Array.from(e.dataTransfer.files);
    if (files.length) await uploadFiles(files);
  }, [disabled, uploadFiles]);

  const handleFileSelect = useCallback(async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length) await uploadFiles(files);
    e.target.value = "";
  }, [uploadFiles]);

  const accepted = "image/*,video/*";

  return (
    <div className="relative">
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={accepted}
        onChange={handleFileSelect}
        className="hidden"
        disabled={disabled || uploading}
        id="file-upload"
      />
      <div
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={() => !disabled && !uploading && inputRef.current?.click()}
        className={`
          border-2 border-dashed rounded-xl p-8 text-center transition-colors
          ${dragActive ? "border-emerald-400 bg-emerald-900/20" : "border-slate-700 hover:border-slate-500"}
          ${disabled || uploading ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
        `}
        role="button"
        tabIndex={0}
        onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inputRef.current?.click(); }}}
      >
        {uploading ? (
          <div className="space-y-3">
            <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-emerald-400 transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-sm text-slate-400">
              {progress >= 90 ? "Elaborazione sul server…" : "Caricamento in corso…"} {progress >= 100 ? "100%" : `${progress}%`}
            </p>
          </div>
        ) : error ? (
          <div className="text-left">
            <div className="mb-2 flex items-center justify-between">
              <div>
                <p className="font-medium text-rose-400">{error.title}</p>
                <p className="text-sm text-rose-200">{error.detail}</p>
              </div>
              <button
                onClick={() => setError(null)}
                className="text-xs underline text-rose-300 hover:text-rose-200"
              >
                Riprova
              </button>
            </div>
            {error.hint && (
              <p className="text-xs text-slate-400 mt-2 p-2 rounded bg-slate-800/50 border border-slate-700">
                💡 {error.hint}
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            <svg
              className="mx-auto h-12 w-12 text-slate-500"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
              />
            </svg>
            <p className="text-slate-300">
              Trascina foto/video qui, o clicca per selezionare
            </p>
            <p className="text-xs text-slate-500">
              Formati: JPG, PNG, WebP, HEIC, MP4, MOV, MKV, WebM&hellip; (max 500MB cadauno)
            </p>
          </div>
        )}
      </div>
    </div>
  );
}