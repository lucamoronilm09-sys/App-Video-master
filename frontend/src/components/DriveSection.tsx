"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  driveAuthUrl,
  driveDisconnect,
  driveListFiles,
  driveStatus,
  isJobActive,
  saveDriveCredentials,
  type DriveEntry,
  type DriveStatus,
  type Job,
  type ProjectState,
} from "@/lib/api";

interface DriveSectionProps {
  projectId: string;
  onSubmitImport: (fileIds: string[], folderIds: string[]) => Promise<Job | { job: Job } | ProjectState>;
  job?: Job | null;
}

function isSupported(e: DriveEntry): boolean {
  if (e.is_folder) return true;
  if (e.mimeType === "image/svg+xml") return false;
  return e.mimeType.startsWith("image/") || e.mimeType.startsWith("video/");
}

function formatDriveError(err: unknown, fallback = "Operazione Drive fallita"): string {
  const msg = err instanceof Error ? err.message : fallback;
  const m = msg.toLowerCase();
  if (m.includes("server non raggiungibile") || m.includes("impossibile raggiungere") || m.includes("network") || m.includes("fetch")) {
    return `Server backend non raggiungibile. Avvia il backend su http://127.0.0.1:8000 o imposta NEXT_PUBLIC_API_URL. Dettaglio: ${msg}`;
  }
  if (m.includes("timeout") || m.includes("scaduta")) {
    return `Timeout: Google Drive non ha risposto in tempo. Riprova più tardi o con una cartella più piccola.`;
  }
  if (m.includes("401") || m.includes("non connesso") || m.includes("autorizzazione mancante") || m.includes("oauth")) {
    return `Sessione Drive scaduta o non valida. Clicca "Connetti Google Drive" per autorizzare nuovamente.`;
  }
  if (m.includes("502") || m.includes("servizio esterno") || m.includes("errore google drive") || m.includes("quota")) {
    return `Google Drive ha restituito un errore: ${msg}. Controlla stato di Google Workspace o riprova più tardi.`;
  }
  if (m.includes("504") || m.includes("gateway")) {
    return `Timeout di gateway durante la comunicazione con Google Drive. Riprova più tardi.`;
  }
  if (m.includes("conflitto") || m.includes("409")) {
    return `C'è già un import Drive in corso per questo progetto. Attendi che termini prima di avviarne un altro.`;
  }
  if (m.includes("400") || m.includes("non valido") || m.includes("seleziona almeno")) {
    return msg;
  }
  return msg;
}

/** Dopo quanti secondi un import ancora "attivo" è sospetto (backend: 300s/file). */
const STUCK_AFTER_SEC = 15 * 60;
/** Dopo quanti secondi senza heartbeat il progress è considerato perso. */
const STALE_AFTER_SEC = 120;

/** M7 + coda: submit import in background, progress live dal job. */
export function DriveSection({ projectId, onSubmitImport, job }: DriveSectionProps) {
  const [status, setStatus] = useState<DriveStatus | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [folderId, setFolderId] = useState("root");
  const [stack, setStack] = useState<{ id: string; name: string }[]>([]);
  const [folderName, setFolderName] = useState("Il mio Drive");
  const [entries, setEntries] = useState<DriveEntry[]>([]);
  const [nextPageToken, setNextPageToken] = useState<string | undefined>(undefined);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<{ id: string; name: string }[]>([]);
  const [sharedView, setSharedView] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const importing = submitting || isJobActive(job);
  // Tick per il watchdog: rivaluta ogni 5s se il job attivo è fermo da troppo.
  const [nowSec, setNowSec] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!importing) return;
    const t = setInterval(() => setNowSec(Date.now() / 1000), 5000);
    return () => clearInterval(t);
  }, [importing]);

  /** Watchdog client-side: se il job resta attivo oltre la soglia o senza
   *  heartbeat, l'import non deve sembrare "in corso" all'infinito. */
  const stuckWarning: string | null = (() => {
    if (!job || !isJobActive(job)) return null;
    const createdMs = typeof job.created_at === "number" ? job.created_at * 1000 : new Date(job.created_at).getTime();
    const updatedMs = typeof job.updated_at === "number" ? job.updated_at * 1000 : new Date(job.updated_at).getTime();
    const elapsed = nowSec - (createdMs / 1000);
    const staleFor = nowSec - (updatedMs / 1000);
    if (staleFor > STALE_AFTER_SEC) {
      const mins = Math.max(1, Math.round(staleFor / 60));
      return `Nessun avanzamento da oltre ${mins} min: la connessione con il server potrebbe essersi interrotta. Ricarica la pagina: se i file non compaiono, riprova l'import.`;
    }
    if (elapsed > STUCK_AFTER_SEC) {
      return `Import attivo da oltre ${Math.round(elapsed / 60)} min: potrebbe essersi bloccato su un file molto grande o su una connessione lenta. Il server interrompe ogni file dopo 5 min con un errore visibile qui sotto; se non succede, ricarica e riprova con meno file.`;
    }
    return null;
  })();

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await driveStatus());
    } catch (err) {
      setStatus(null);
      setError(formatDriveError(err, "Impossibile leggere lo stato Drive"));
    }
  }, []);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === "drive-connected") {
        void refreshStatus();
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [refreshStatus]);

  useEffect(() => {
    refreshStatus();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refreshStatus]);

  const loadFolder = useCallback(async (fid: string, shared = false, pageToken?: string) => {
    setBusy(true);
    setError(null);
    console.info(`[Drive] lettura cartella fid=${fid} shared=${shared}`);
    try {
      const data = await driveListFiles(projectId, fid, pageToken);
      console.info(`[Drive] cartella '${data.current.name}': ${data.entries.length} voci`);
      setFolderId(data.current.id);
      setFolderName(data.current.name);
      setEntries(pageToken ? prev => [...prev, ...data.entries] : data.entries);
      setNextPageToken(data.nextPageToken);
      setSharedView(shared);
      if (!shared) {
        if (fid === "root") {
          setStack([]);
        }
      } else {
        setStack([]);
      }
    } catch (err) {
      console.error("[Drive] lettura cartella fallita:", err);
      setError(formatDriveError(err, "Lettura cartella Drive fallita"));
      setEntries([]);
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (status?.connected) void loadFolder("root");
  }, [status?.connected, loadFolder]);

  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const handleSaveCredentials = async () => {
    setBusy(true);
    setError(null);
    try {
      await saveDriveCredentials(clientId, clientSecret);
      setClientSecret("");
      await refreshStatus();
    } catch (err) {
      setError(formatDriveError(err, "Salvataggio credenziali fallito"));
    } finally {
      setBusy(false);
    }
  };

  const handleConnect = async () => {
    setError(null);
    try {
      const url = await driveAuthUrl();
      window.open(url, "_blank", "width=520,height=640");
      stopPoll();
      let tries = 0;
      pollRef.current = setInterval(async () => {
        tries += 1;
        const s = await driveStatus().catch(() => null);
        if (s?.connected || tries > 90) {
          stopPoll();
          if (s) setStatus(s);
        }
      }, 2000);
    } catch (err) {
      setError(formatDriveError(err, "Connessione a Drive fallita"));
    }
  };

  const handleDisconnect = async () => {
    await driveDisconnect().catch(() => null);
    setEntries([]);
    setSelectedFiles([]);
    setSelectedFolders([]);
    setStack([]);
    await refreshStatus();
  };

  const navigate = (id: string) => {
    setStack(prev => [...prev, { id: folderId, name: folderName }]);
    void loadFolder(id, false);
  };

  const goBack = () => {
    const prev = stack[stack.length - 1];
    if (!prev) return;
    setStack(s => s.slice(0, -1));
    void loadFolder(prev.id, false);
  };

  const handleViewMode = (shared: boolean) => {
    setSelectedFiles([]);
    setSelectedFolders([]);
    setStack([]);
    if (shared) {
      void loadFolder("shared", true);
    } else {
      void loadFolder("root", false);
    }
  };

  const toggleFile = (id: string) => {
    setSelectedFiles(prev => (prev.includes(id) ? prev.filter(f => f !== id) : [...prev, id]));
  };

  const toggleFolder = (id: string, name: string) => {
    setSelectedFolders(prev =>
      prev.some(f => f.id === id) ? prev.filter(f => f.id !== id) : [...prev, { id, name }],
    );
  };

  const handleImport = async () => {
    setSubmitting(true);
    setError(null);
    const nFiles = selectedFiles.length;
    const nFolders = selectedFolders.length;
    console.info(`[Drive] avvio import: ${nFiles} file + ${nFolders} cartelle`);
    try {
      const result = await onSubmitImport(selectedFiles, selectedFolders.map(f => f.id));
      // Il backend può ritornare ProjectState (sync) o {job: Job} (background)
      const jobId = 'job' in result ? result.job.id : ('project_id' in result ? 'inline' : 'unknown');
      console.info(`[Drive] import accodato job=${jobId}; avanzamento via SSE`);
      setSelectedFiles([]);
      setSelectedFolders([]);
    } catch (err) {
      console.error("[Drive] submit import fallito:", err);
      setError(formatDriveError(err, "Import Drive fallito"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section aria-label="Import da Google Drive" className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
          Google Drive
        </h3>
        {status?.connected && status.email && (
          <span className="truncate text-xs text-slate-500">{status.email}</span>
        )}
      </div>

      {error && (
        <div className="mb-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">
          <p className="font-medium text-rose-300 mb-1">Errore Drive</p>
          <p>{error}</p>
          {(error.includes("Server backend") || error.includes("non raggiungibile")) && (
            <p className="text-xs text-rose-300/80 mt-2 p-2 rounded bg-rose-950/50 border border-rose-800/50">
              💡 Suggerimenti: (1) avvia il backend con <code className="text-[10px]">uvicorn app.main:app --host 127.0.0.1 --port 8000</code> dalla cartella backend; (2) in produzione imposta <code className="text-[10px]">NEXT_PUBLIC_API_URL</code> e <code className="text-[10px]">CORS_ORIGINS</code> lato backend.
            </p>
          )}
          <button
            onClick={() => setError(null)}
            className="mt-2 text-xs underline hover:text-rose-100"
          >
            Chiudi
          </button>
        </div>
      )}

      {!status?.configured ? (
        <div className="space-y-2 text-sm">
          <p className="text-slate-400">
            Incolla le credenziali OAuth (Google Cloud Console → API e servizi → Credenziali →
            ID client OAuth tipo &ldquo;App web&rdquo;, con redirect{" "}
            <code className="text-xs text-slate-300">http://127.0.0.1:8000/api/drive/callback</code>{" "}
            e API Drive abilitata). In produzione sostituisci l&rsquo;host con il valore di <code className="text-xs">DRIVE_HOST</code>.
          </p>
          <input
            value={clientId}
            onChange={e => setClientId(e.target.value)}
            placeholder="Client ID"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200"
          />
          <input
            value={clientSecret}
            onChange={e => setClientSecret(e.target.value)}
            placeholder="Client secret"
            type="password"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200"
          />
          <button
            type="button"
            disabled={busy || !clientId.trim() || !clientSecret.trim()}
            onClick={handleSaveCredentials}
            className="rounded-lg bg-slate-700 px-3 py-1.5 text-sm text-white hover:bg-slate-600 disabled:opacity-50"
          >
            Salva credenziali
          </button>
        </div>
      ) : !status.connected ? (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleConnect}
            className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500"
          >
            Connetti Google Drive
          </button>
          <button
            type="button"
            onClick={() => { setClientId(""); setClientSecret(""); setStatus(s => (s ? { ...s, configured: false } : s)); }}
            className="text-xs text-slate-500 hover:text-slate-300"
          >
            cambia credenziali
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => handleViewMode(false)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium ${!sharedView ? "bg-sky-600 text-white hover:bg-sky-500" : "bg-slate-700 text-slate-300 hover:bg-slate-600"}`}
            >
              Il mio Drive
            </button>
            <button
              type="button"
              onClick={() => handleViewMode(true)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium ${sharedView ? "bg-sky-600 text-white hover:bg-sky-500" : "bg-slate-700 text-slate-300 hover:bg-slate-600"}`}
            >
              Condivisi con me
            </button>
          </div>


          {nextPageToken && !busy && (
            <button
              type="button"
              onClick={() => void loadFolder(folderId, sharedView, nextPageToken)}
              className="w-full rounded-lg bg-slate-800 px-3 py-2 text-xs text-slate-300 hover:bg-slate-700"
            >
              Carica altri file
            </button>
          )}
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2 text-sm">
              {stack.length > 0 && (
                <button type="button" onClick={goBack} className="rounded px-1.5 py-0.5 text-slate-300 hover:bg-slate-700" aria-label="Cartella precedente">
                  ←
                </button>
              )}
              <span className="truncate font-medium text-slate-200">{busy ? "…" : folderName}</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void loadFolder(sharedView ? "shared" : folderId, sharedView)}
                className="text-xs text-slate-400 hover:text-slate-200"
                aria-label="Ricarica cartella"
                title="Ricarica cartella"
                disabled={busy}
              >
                ⟳
              </button>
              <button type="button" onClick={handleDisconnect} className="shrink-0 text-xs text-slate-500 hover:text-slate-300">
                disconnetti
              </button>
            </div>
          </div>

          <ul className="max-h-56 space-y-1 overflow-y-auto pr-1">
            {entries.map(e => {
              const supported = isSupported(e);
              const checked = e.is_folder
                ? selectedFolders.some(f => f.id === e.id)
                : selectedFiles.includes(e.id);
              return (
                <li
                  key={e.id}
                  className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm ${supported ? "bg-slate-800/70" : "bg-slate-800/30 opacity-50"}`}
                  title={supported ? e.mimeType : `${e.mimeType} — non supportato`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!supported}
                    onChange={() => (e.is_folder ? toggleFolder(e.id, e.name) : toggleFile(e.id))}
                    aria-label={`Seleziona ${e.name}`}
                  />
                  {e.is_folder ? (
                    <button
                      type="button"
                      onClick={() => navigate(e.id)}
                      className="flex-1 truncate text-left text-sky-300 hover:underline"
                      disabled={busy && !supported}
                    >
                      📁 {e.name}
                    </button>
                  ) : (
                    <span className="flex-1 truncate text-slate-300">
                      {e.mimeType.startsWith("video/") ? "🎬" : "🖼️"} {e.name}
                    </span>
                  )}
                </li>
              );
            })}
            {entries.length === 0 && !busy && (
              <li className="py-4 text-center text-sm text-slate-500">Cartella vuota</li>
            )}
          </ul>

          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-slate-500">
              {selectedFiles.length} file · {selectedFolders.length} cartelle (ricorsive)
            </p>
            <button
              type="button"
              disabled={importing || (selectedFiles.length === 0 && selectedFolders.length === 0)}
              onClick={handleImport}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              {importing ? "Import in corso…" : "⬇ Importa nel progetto"}
            </button>
          </div>
          {importing && (
            <div className="space-y-1" aria-label="Avanzamento import">
              <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                <div
                  className="h-full rounded-full bg-sky-500 transition-all duration-500"
                  style={{ width: `${Math.round((job && isJobActive(job) ? (job.progress?.fraction ?? 0) : 0) * 100)}%` }}
                />
              </div>
              <p className="text-xs text-slate-500">
                {job && isJobActive(job) && job.status === "running"
                  ? `Download da Drive… ${Math.round((job.progress?.fraction ?? 0) * 100)}%${job.progress?.note ? ` · ${job.progress.note}` : ""}`
                  : "Download in corso… i file appariranno in timeline da soli. Se fallisce, verifica la connessione e che il backend sia raggiungibile."}
              </p>
              {stuckWarning && (
                <p className="rounded border border-amber-700 bg-amber-900/20 px-2 py-1.5 text-xs text-amber-200">
                  ⚠️ {stuckWarning}
                </p>
              )}
            </div>
          )}
          {job?.status === "failed" && (
            <div className="rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">
              <p className="font-medium text-rose-300 mb-1">Import fallito</p>
              <p>{job.error ?? "errore sconosciuto"}</p>
              <p className="text-xs text-rose-300/80 mt-2 p-2 rounded bg-rose-950/50 border border-rose-800/50">
                💡 Se compare &ldquo;failed to fetch&rdquo; o errori di rete: verifica che il backend sia attivo, che <code className="text-[10px]">CORS_ORIGINS</code> includa il frontend e che Google Drive sia raggiungibile.
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
