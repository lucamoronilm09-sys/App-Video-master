"use client";

import { useCallback, useRef, useState, DragEvent, ChangeEvent } from "react";
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

  const uploadFiles = useCallback(async (files: File[]) => {
    const MAX_SELECTION = 500;
    const BATCH_SIZE = 20;
    if (files.length > MAX_SELECTION) {
      setError({ title: "Troppi file", detail: `Puoi selezionare fino a ${MAX_SELECTION} foto/video per volta.`, hint: "La selezione viene poi inviata automaticamente in piccoli lotti." });
      return;
    }
    setUploading(true);
    setProgress(0);
    setError(null);
    try {
      const batches = Math.ceil(files.length / BATCH_SIZE);
      for (let i = 0; i < batches; i++) {
        const batch = files.slice(i * BATCH_SIZE, (i + 1) * BATCH_SIZE);
        await uploadMedia(projectId, batch);
        setProgress(Math.round(((i + 1) / batches) * 100));
        await onUploadComplete(batch.length);
      }
    } catch (err) {
      setError(formatError(err));
    } finally {
      setTimeout(() => { setUploading(false); setProgress(0); }, 700);
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
    if (!disabled) {
      const files = Array.from(e.dataTransfer.files);
      if (files.length) await uploadFiles(files);
    }
  }, [disabled, uploadFiles]);

  const handleFileSelect = useCallback(async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length) await uploadFiles(files);
    e.target.value = "";
  }, [uploadFiles]);

  return (
    <div className="relative">
      <input
        ref={inputRef}
        type="file"
        multiple
        accept="image/*,video/*"
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
        className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors ${dragActive ? "border-emerald-400 bg-emerald-900/20" : "border-slate-700 hover:border-slate-500"} ${disabled || uploading ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
        role="button"
        tabIndex={0}
        onKeyDown={e => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
      >
        {uploading ? (
          <div className="space-y-3">
            <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full bg-emerald-400 transition-all duration-300" style={{ width: `${progress}%` }} />
            </div>
            <p className="text-sm text-slate-400">Caricamento a lotti… {progress}%</p>
          </div>
        ) : error ? (
          <div className="text-left">
            <p className="font-medium text-rose-400">{error.title}</p>
            <p className="text-sm text-rose-200">{error.detail}</p>
            {error.hint && <p className="text-xs text-slate-400 mt-2 p-2 rounded bg-slate-800/50 border border-slate-700">{error.hint}</p>}
            <button onClick={(e) => { e.stopPropagation(); setError(null); }} className="text-xs underline text-rose-300 mt-2">Chiudi</button>
          </div>
        ) : (
          <div className="space-y-2">
            <p className="text-slate-300">Trascina foto/video qui, o clicca per selezionare</p>
            <p className="text-xs text-slate-500">Fino a 500 foto/video per selezione · invio automatico a lotti da 20 · max 500MB ciascuno</p>
          </div>
        )}
      </div>
    </div>
  );
}
