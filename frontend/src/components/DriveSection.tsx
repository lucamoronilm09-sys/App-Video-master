"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { driveAuthUrl, driveDisconnect, driveListFiles, driveStatus, isJobActive, saveDriveCredentials, type DriveEntry, type DriveStatus, type Job, type ProjectState } from "@/lib/api";

interface DriveSectionProps {
  projectId: string;
  onSubmitImport: (fileIds: string[], folderIds: string[]) => Promise<Job | { job: Job } | ProjectState>;
  job?: Job | null;
}

function isSupported(entry: DriveEntry): boolean {
  if (entry.is_folder) return true;
  if (entry.mimeType === "image/svg+xml") return false;
  return entry.mimeType.startsWith("image/") || entry.mimeType.startsWith("video/");
}

function formatDriveError(err: unknown, fallback = "Operazione Drive fallita"): string {
  const msg = err instanceof Error ? err.message : fallback;
  const lower = msg.toLowerCase();
  if (lower.includes("fetch") || lower.includes("network") || lower.includes("server non raggiungibile")) return `Backend non raggiungibile. Verifica che l'app sia avviata su http://localhost:3000 e il backend su http://127.0.0.1:8000. Dettaglio: ${msg}`;
  if (lower.includes("401") || lower.includes("oauth") || lower.includes("non connesso")) return "Sessione Google Drive non valida o scaduta. Riconnetti l'account.";
  if (lower.includes("409") || lower.includes("conflitto")) return "C'è già un import Drive in corso per questo progetto. Attendi che termini.";
  return msg;
}

const STALE_AFTER_SEC = 120;

export function DriveSection({ projectId, onSubmitImport, job }: DriveSectionProps) {
  const [status, setStatus] = useState<DriveStatus | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [folderId, setFolderId] = useState("root");
  const [folderName, setFolderName] = useState("Il mio Drive");
  const [stack, setStack] = useState<{ id: string; name: string }[]>([]);
  const [entries, setEntries] = useState<DriveEntry[]>([]);
  const [nextPageToken, setNextPageToken] = useState<string | undefined>();
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<{ id: string; name: string }[]>([]);
  const [sharedView, setSharedView] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const importing = submitting || isJobActive(job);

  const refreshStatus = useCallback(async () => {
    try { setStatus(await driveStatus()); }
    catch (err) { setStatus(null); setError(formatDriveError(err, "Impossibile leggere lo stato di Google Drive")); }
  }, []);

  const loadFolder = useCallback(async (id: string, shared = false, pageToken?: string) => {
    setBusy(true); setError(null);
    try {
      const data = await driveListFiles(projectId, { folderId: id, pageToken, shared });
      setFolderId(data.current.id);
      setFolderName(data.current.name);
      setNextPageToken(data.nextPageToken);
      setEntries(pageToken ? prev => [...prev, ...data.entries] : data.entries);
      setSharedView(shared);
      if (!pageToken) setStack([]);
    } catch (err) {
      setError(formatDriveError(err, "Lettura cartella Drive fallita"));
      if (!pageToken) setEntries([]);
    } finally { setBusy(false); }
  }, [projectId]);

  useEffect(() => {
    void refreshStatus();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [refreshStatus]);

  useEffect(() => {
    if (status?.connected) void loadFolder("root", false);
  }, [status?.connected, loadFolder]);

  const stopPoll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  const handleSaveCredentials = async () => {
    setBusy(true); setError(null);
    try { await saveDriveCredentials(clientId, clientSecret); setClientSecret(""); await refreshStatus(); }
    catch (err) { setError(formatDriveError(err, "Salvataggio credenziali fallito")); }
    finally { setBusy(false); }
  };

  const handleConnect = async () => {
    setError(null);
    try {
      const url = await driveAuthUrl();
      window.open(url, "_blank", "width=520,height=680");
      stopPoll();
      let tries = 0;
      pollRef.current = setInterval(async () => {
        tries += 1;
        const next = await driveStatus().catch(() => null);
        if (next?.connected || tries >= 90) { stopPoll(); if (next) setStatus(next); }
      }, 2000);
    } catch (err) { setError(formatDriveError(err, "Connessione a Google Drive fallita")); }
  };

  const handleDisconnect = async () => {
    stopPoll();
    await driveDisconnect().catch(() => null);
    setEntries([]); setSelectedFiles([]); setSelectedFolders([]); setStack([]);
    setFolderId("root"); setFolderName("Il mio Drive"); await refreshStatus();
  };

  const toggleFile = (id: string) => setSelectedFiles(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  const toggleFolder = (id: string, name: string) => setSelectedFolders(prev => prev.some(x => x.id === id) ? prev.filter(x => x.id !== id) : [...prev, { id, name }]);

  const supportedFiles = useMemo(() => entries.filter(e => !e.is_folder && isSupported(e)), [entries]);
  const selectableEntries = useMemo(() => entries.filter(isSupported), [entries]);
  const allVisibleSelected = selectableEntries.length > 0 && selectableEntries.every(e => e.is_folder ? selectedFolders.some(f => f.id === e.id) : selectedFiles.includes(e.id));

  const toggleAllVisible = () => {
    if (allVisibleSelected) {
      const files = new Set(supportedFiles.map(e => e.id));
      const folders = new Set(entries.filter(e => e.is_folder && isSupported(e)).map(e => e.id));
      setSelectedFiles(prev => prev.filter(id => !files.has(id)));
      setSelectedFolders(prev => prev.filter(f => !folders.has(f.id)));
      return;
    }
    setSelectedFiles(prev => Array.from(new Set([...prev, ...supportedFiles.map(e => e.id)])));
    setSelectedFolders(prev => {
      const map = new Map(prev.map(f => [f.id, f]));
      for (const e of entries.filter(x => x.is_folder && isSupported(x))) map.set(e.id, { id: e.id, name: e.name });
      return Array.from(map.values());
    });
  };

  const navigate = (id: string) => {
    setStack(prev => [...prev, { id: folderId, name: folderName }]);
    void loadFolder(id, false);
  };

  const goBack = () => {
    const previous = stack[stack.length - 1];
    if (!previous) return;
    setStack(prev => prev.slice(0, -1));
    void loadFolder(previous.id, false);
  };

  const setView = (shared: boolean) => {
    setSelectedFiles([]); setSelectedFolders([]); setStack([]);
    void loadFolder(shared ? "shared" : "root", shared);
  };

  const handleImport = async () => {
    if (!selectedFiles.length && !selectedFolders.length) return;
    setSubmitting(true); setError(null);
    try {
      await onSubmitImport(selectedFiles, selectedFolders.map(f => f.id));
      setSelectedFiles([]); setSelectedFolders([]);
    } catch (err) { setError(formatDriveError(err, "Import Drive fallito")); }
    finally { setSubmitting(false); }
  };

  const staleWarning = useMemo(() => {
    if (!job || !isJobActive(job)) return null;
    const updated = typeof job.updated_at === "number" ? job.updated_at : new Date(job.updated_at).getTime() / 1000;
    return Date.now() / 1000 - updated > STALE_AFTER_SEC ? "Il server non segnala avanzamenti da oltre 2 minuti. Controlla il job prima di rilanciare l'import." : null;
  }, [job]);

  if (!status?.configured) return (
    <section aria-label="Import da Google Drive" className="min-w-0 rounded-2xl border border-slate-700 bg-slate-900/50 p-4">
      <div className="mb-3"><h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300">Import</h3><p className="mt-1 text-xs text-slate-500">Collega Google Drive per aggiungere foto e video al progetto.</p></div>
      {error && <p className="mb-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">{error}</p>}
      <div className="grid gap-2 sm:grid-cols-2"><input value={clientId} onChange={e => setClientId(e.target.value)} placeholder="Client ID" className="min-w-0 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200" /><input value={clientSecret} onChange={e => setClientSecret(e.target.value)} placeholder="Client secret" type="password" className="min-w-0 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200" /></div>
      <button type="button" disabled={busy || !clientId.trim() || !clientSecret.trim()} onClick={handleSaveCredentials} className="mt-3 rounded-lg bg-slate-700 px-3 py-2 text-sm font-medium text-white hover:bg-slate-600 disabled:opacity-50">Salva credenziali</button>
    </section>
  );

  if (!status.connected) return (
    <section aria-label="Import da Google Drive" className="min-w-0 rounded-2xl border border-slate-700 bg-slate-900/50 p-4">
      {error && <p className="mb-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">{error}</p>}
      <div className="flex flex-wrap items-center gap-3"><button type="button" onClick={handleConnect} className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-500">Connetti Google Drive</button><button type="button" onClick={() => { setClientId(""); setClientSecret(""); setStatus(s => s ? { ...s, configured: false } : s); }} className="text-xs text-slate-500 hover:text-slate-300">cambia credenziali</button></div>
    </section>
  );

  return (
    <section aria-label="Import da Google Drive" className="min-w-0 rounded-2xl border border-slate-700 bg-slate-900/50 p-4">
      <div className="mb-4 flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300">Import</h3>{status.email && <span className="max-w-full truncate text-xs text-slate-500">{status.email}</span>}</div><p className="mt-1 text-xs text-slate-500">Clicca una foto o un video per selezionarlo; puoi selezionarne più di uno.</p></div><button type="button" onClick={handleDisconnect} className="self-start text-xs text-slate-500 hover:text-slate-300">Disconnetti</button></div>
      {error && <div className="mb-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">{error}</div>}

      <div className="flex flex-wrap gap-2"><button type="button" onClick={() => setView(false)} className={`rounded-lg px-3 py-2 text-sm font-medium ${!sharedView ? "bg-sky-600 text-white" : "bg-slate-700 text-slate-300 hover:bg-slate-600"}`}>Il mio Drive</button><button type="button" onClick={() => setView(true)} className={`rounded-lg px-3 py-2 text-sm font-medium ${sharedView ? "bg-sky-600 text-white" : "bg-slate-700 text-slate-300 hover:bg-slate-600"}`}>Condivisi con me</button></div>

      <div className="mt-3 flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2"><div className="flex min-w-0 items-center gap-2 text-sm">{stack.length > 0 && <button type="button" onClick={goBack} aria-label="Cartella precedente" className="rounded px-2 py-1 text-slate-300 hover:bg-slate-800">←</button>}<span className="truncate font-medium text-slate-200">{busy ? "Caricamento…" : folderName}</span></div><button type="button" onClick={() => void loadFolder(folderId, sharedView)} disabled={busy} className="rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-800 hover:text-white disabled:opacity-50" title="Ricarica">⟳</button></div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2"><button type="button" disabled={busy || selectableEntries.length === 0} onClick={toggleAllVisible} className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-50">{allVisibleSelected ? "Deseleziona tutto" : "Seleziona tutto"}</button><span className="text-xs text-slate-500">{supportedFiles.length} media visibili · {selectedFiles.length} selezionati{selectedFolders.length ? ` · ${selectedFolders.length} cartelle` : ""}</span></div>
      {nextPageToken && !busy && <button type="button" onClick={() => void loadFolder(folderId, sharedView, nextPageToken)} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-slate-300 hover:bg-slate-700">Carica altri file</button>}

      <ul className="mt-3 max-h-80 space-y-1 overflow-y-auto pr-1">
        {entries.map(entry => {
          const supported = isSupported(entry);
          const checked = entry.is_folder ? selectedFolders.some(f => f.id === entry.id) : selectedFiles.includes(entry.id);
          return (
            <li key={entry.id}
              onClick={() => { if (supported && !entry.is_folder && !busy) toggleFile(entry.id); }}
              className={`flex min-w-0 items-center gap-2 rounded-lg border px-2 py-2 text-sm transition ${!supported ? "border-transparent bg-slate-800/30 opacity-45" : checked ? "border-sky-500/70 bg-sky-500/15 ring-1 ring-sky-500/30" : "border-transparent bg-slate-800/70 hover:border-slate-600 hover:bg-slate-700/80 cursor-pointer"}`}
            >
              <input type="checkbox" checked={checked} disabled={!supported || busy} onChange={() => entry.is_folder ? toggleFolder(entry.id, entry.name) : toggleFile(entry.id)} onClick={e => e.stopPropagation()} aria-label={`Seleziona ${entry.name}`} />
              {entry.is_folder ? <button type="button" disabled={busy} onClick={() => navigate(entry.id)} className="min-w-0 flex-1 truncate text-left text-sky-300 hover:underline">📁 {entry.name}</button> : <span className={`min-w-0 flex-1 truncate ${checked ? "font-medium text-sky-100" : "text-slate-300"}`}>{entry.mimeType.startsWith("video/") ? "🎬" : "🖼️"} {entry.name}</span>}
              {checked && !entry.is_folder && <span className="shrink-0 text-xs font-semibold text-sky-300">Selezionato</span>}
            </li>
          );
        })}
        {!entries.length && !busy && <li className="py-6 text-center text-sm text-slate-500">Nessun file disponibile.</li>}
      </ul>

      <div className="mt-4 flex flex-col gap-3 rounded-xl border border-slate-800 bg-slate-950/40 p-3 sm:flex-row sm:items-center sm:justify-between"><div className="text-xs text-slate-500"><p>{selectedFiles.length} file selezionati · {selectedFolders.length} cartelle</p><p className="mt-1">L&apos;import aggiunge i file al progetto esistente senza rimuovere quelli locali.</p></div><button type="button" disabled={importing || (!selectedFiles.length && !selectedFolders.length)} onClick={handleImport} className="shrink-0 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50">{importing ? "Import in corso…" : "Importa selezionati"}</button></div>
      {importing && job && <div className="mt-3 space-y-1" aria-label="Avanzamento import"><div className="h-2 overflow-hidden rounded-full bg-slate-800"><div className="h-full rounded-full bg-sky-500 transition-all duration-500" style={{ width: `${Math.round((job.progress?.fraction ?? 0) * 100)}%` }} /></div><p className="text-xs text-slate-500">{job.status === "pending" ? "In coda…" : `${job.progress?.note ?? "Download da Drive"} · ${Math.round((job.progress?.fraction ?? 0) * 100)}%`}</p>{staleWarning && <p className="rounded-lg border border-amber-700 bg-amber-900/20 px-3 py-2 text-xs text-amber-200">⚠ {staleWarning}</p>}</div>}
      {job?.status === "failed" && <div className="mt-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200"><p className="font-medium text-rose-300">Import fallito</p><p className="mt-1 break-words">{job.error ?? "Errore sconosciuto"}</p></div>}
    </section>
  );
}
