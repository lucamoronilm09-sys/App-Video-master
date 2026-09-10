"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  clearErrors, getProject, patchClipOverride, planEdit, reorderMedia,
  resetClipOverride, submitDriveImportJob, submitRenderJob, updateMediaFill,
  updateSettings, uploadAudio, type BackgroundFill, type ClipOverride,
  type Job, type ProjectState, type SettingsPatch,
} from "@/lib/api";
import { useProjectEvents } from "@/hooks/useProjectEvents";
import { UploadZone } from "@/components/UploadZone";
import { DriveSection } from "@/components/DriveSection";
import { AudioSection } from "@/components/AudioSection";
import { MontageSection } from "@/components/MontageSection";
import { ExportSection } from "@/components/ExportSection";
import { Timeline } from "@/components/Timeline";
import { ProjectSettings } from "@/components/ProjectSettings";
import { PipelineProgress } from "@/components/PipelineProgress";
import { ErrorPanel } from "@/components/ErrorPanel";

export default function ProjectPage() {
  const params = useParams();
  const router = useRouter();
  const projectId = params.id as string;
  const [project, setProject] = useState<ProjectState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [timelineBusy, setTimelineBusy] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [audioBusy, setAudioBusy] = useState(false);
  const [editBusy, setEditBusy] = useState(false);
  const [clearBusy, setClearBusy] = useState(false);
  const progress = useProjectEvents(projectId);
  const lastSyncRef = useRef(0);
  const syncingRef = useRef(false);

  const lastJob = (kind: Job["kind"]): Job | null =>
    (progress?.jobs ?? []).find((j: Job) => j.kind === kind) ?? null;

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        setProject(await getProject(projectId));
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore caricamento progetto");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [projectId]);

  const handleUploadComplete = useCallback(async () => {
    try { setProject(await getProject(projectId)); } catch { /* UploadZone mostra già l'errore. */ }
  }, [projectId]);

  const handleReorder = useCallback(async (mediaIds: string[]) => {
    const prev = project;
    if (!prev) return;
    const byId = new Map(prev.media.map(m => [m.id, m]));
    setProject({ ...prev, media: mediaIds.map((id, i) => ({ ...byId.get(id)!, order_index: i })) });
    setTimelineBusy(true);
    try { setProject(await reorderMedia(projectId, mediaIds)); }
    catch (err) { setProject(prev); throw err; }
    finally { setTimelineBusy(false); }
  }, [project, projectId]);

  const handleToggleFill = useCallback(async (mediaId: string, fill: BackgroundFill) => {
    setTimelineBusy(true);
    try { setProject(await updateMediaFill(projectId, mediaId, fill)); }
    finally { setTimelineBusy(false); }
  }, [projectId]);

  const handleSettings = useCallback(async (patch: SettingsPatch) => {
    setSettingsBusy(true);
    try { setProject(await updateSettings(projectId, patch)); }
    catch (err) { setError(err instanceof Error ? err.message : "Salvataggio impostazioni fallito"); }
    finally { setSettingsBusy(false); }
  }, [projectId]);

  const handleAudioUpload = useCallback(async (file: File) => {
    setAudioBusy(true);
    try { setProject(await uploadAudio(projectId, file)); }
    finally { setAudioBusy(false); }
  }, [projectId]);

  const handleGenerateEdit = useCallback(async () => {
    setEditBusy(true);
    try { setProject(await planEdit(projectId)); }
    finally { setEditBusy(false); }
  }, [projectId]);

  const handlePatchClip = useCallback(async (mediaId: string, patch: ClipOverride) => {
    setEditBusy(true);
    try { setProject(await patchClipOverride(projectId, mediaId, patch)); }
    finally { setEditBusy(false); }
  }, [projectId]);

  const handleResetClip = useCallback(async (mediaId: string) => {
    setEditBusy(true);
    try { setProject(await resetClipOverride(projectId, mediaId)); }
    finally { setEditBusy(false); }
  }, [projectId]);

  const handleSubmitRender = useCallback(() => submitRenderJob(projectId), [projectId]);
  const handleSubmitDriveImport = useCallback((fileIds: string[], folderIds: string[]) =>
    submitDriveImportJob(projectId, fileIds, folderIds, true), [projectId]);
  const handleClearErrors = useCallback(async () => {
    setClearBusy(true);
    try { setProject(await clearErrors(projectId)); }
    finally { setClearBusy(false); }
  }, [projectId]);

  useEffect(() => {
    if (!progress || !project || syncingRef.current) return;
    if (progress.updated_at <= project.updated_at) return;
    if (Date.now() - lastSyncRef.current < 3000) return;
    lastSyncRef.current = Date.now();
    syncingRef.current = true;
    getProject(projectId).then(setProject).catch(() => null).finally(() => { syncingRef.current = false; });
  }, [progress, project, projectId]);

  if (loading) return (
    <main className="app-shell flex min-h-screen items-center justify-center px-6">
      <div className="text-center"><div className="glow mx-auto h-11 w-11 animate-spin rounded-full border-2 border-violet-400 border-t-transparent" /><p className="mt-5 text-sm text-slate-400">Preparazione workspace…</p></div>
    </main>
  );

  if (error && !project) return (
    <main className="app-shell flex min-h-screen items-center justify-center px-6">
      <div className="surface max-w-md rounded-3xl p-8 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-rose-400/10 text-rose-300">!</div>
        <p className="mt-4 text-rose-300">{error}</p>
        <button onClick={() => router.push("/")} className="mt-5 rounded-xl bg-white px-4 py-2 text-sm font-semibold text-slate-950">Torna alla home</button>
      </div>
    </main>
  );

  return (
    <main className="app-shell min-h-screen px-4 py-6 sm:px-6 lg:px-10">
      <div className="mx-auto max-w-7xl">
        <header className="surface sticky top-4 z-40 mb-6 flex items-center justify-between rounded-2xl px-4 py-3">
          <div className="flex items-center gap-3">
            <button onClick={() => router.push("/")} className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/5 text-slate-300 transition hover:bg-white/10">←</button>
            <div><p className="text-sm font-semibold text-white">AI Video Maker</p><p className="text-[11px] text-slate-500">Editing workspace</p></div>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-400 sm:block">{project?.media.length || 0} asset</span>
            <span className="rounded-full border border-emerald-400/15 bg-emerald-400/10 px-3 py-1.5 text-xs font-medium text-emerald-300">● Progetto attivo</span>
          </div>
        </header>

        <section className="surface float-in rounded-3xl p-5 sm:p-7">
          <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Project workspace</p>
              <h1 className="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Progetto <span className="gradient-text">{project?.project_id?.slice(0, 8)}</span></h1>
              <p className="mt-2 text-sm text-slate-500">Costruisci il video passo dopo passo: importa, ordina, sincronizza, monta e renderizza.</p>
            </div>
            <div className="grid grid-cols-3 gap-2 sm:min-w-[360px]">
              {[["01", "Import"], ["02", "Montaggio"], ["03", "Export"]].map(([n, label]) => <div key={n} className="surface-soft rounded-2xl px-3 py-3"><p className="text-[10px] font-bold text-violet-300">{n}</p><p className="mt-1 text-xs font-semibold text-white">{label}</p></div>)}
            </div>
          </div>
        </section>

        <div className="mt-6 grid gap-6">
          {progress && <section className="surface rounded-3xl p-5"><PipelineProgress log={progress.pipeline_log} /></section>}

          {/* 01 — Import locale */}
          <section className="surface rounded-3xl p-5 sm:p-6">
            <div className="mb-4 flex items-end justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">01 · Media library</p><h2 className="mt-1 text-xl font-bold text-white">Aggiungi contenuti</h2></div><span className="text-xs text-slate-500">Foto e video · max 500 MB</span></div>
            {project && <UploadZone projectId={projectId} onUploadComplete={handleUploadComplete} />}
          </section>

          {/* 02 — Google Drive */}
          {project && <section className="surface rounded-3xl p-5"><DriveSection projectId={projectId} onSubmitImport={handleSubmitDriveImport} job={lastJob("drive_import")} /></section>}

          {/* 03 — Ordine delle clip */}
          {project && <section className="surface rounded-3xl p-5 sm:p-6"><Timeline projectId={projectId} media={project.media} onReorder={handleReorder} onToggleFill={handleToggleFill} busy={timelineBusy} /></section>}

          {/* 04 — Musica */}
          {project && <section className="surface rounded-3xl p-5"><AudioSection audio={project.audio} tracks={project.audio_tracks ?? []} onUpload={handleAudioUpload} busy={audioBusy} /></section>}

          {/* 05 — Impostazioni output */}
          {project && <section className="surface rounded-3xl p-5"><ProjectSettings spec={project.output_spec} onSave={handleSettings} busy={settingsBusy} media={project.media} /></section>}

          {/* 06 — Montaggio IA */}
          {project && <section className="surface rounded-3xl p-5"><MontageSection project={project} onGenerate={handleGenerateEdit} onPatchClip={handlePatchClip} onResetClip={handleResetClip} busy={editBusy} /></section>}

          {/* 07 — Export */}
          {project && <section className="surface rounded-3xl p-5"><ExportSection project={project} onSubmit={handleSubmitRender} job={lastJob("render")} /></section>}

          {error && <div className="rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>}
          {project && <section className="surface rounded-3xl p-5"><ErrorPanel errors={project.errors} onClear={handleClearErrors} busy={clearBusy} /></section>}
        </div>

        <footer className="py-10 text-center text-xs text-slate-600">{project?.project_id} · AI Video Maker</footer>
      </div>
    </main>
  );
}
