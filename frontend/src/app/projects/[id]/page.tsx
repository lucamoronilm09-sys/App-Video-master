"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  clearErrors,
  deleteProject,
  getProject,
  patchClipOverride,
  planEdit,
  reorderMedia,
  resetClipOverride,
  submitDriveImportJob,
  submitRenderJob,
  updateMediaFill,
  updateSettings,
  uploadAudio,
  type BackgroundFill,
  type ClipOverride,
  type Job,
  type ProjectState,
  type SettingsPatch,
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
  const [deleting, setDeleting] = useState(false);
  const progress = useProjectEvents(projectId);
  const lastSyncRef = useRef(0);
  const syncingRef = useRef(false);

  /** Ultimo job noto del kind (qualunque stato): così un import/render
   *  fallito resta visibile con il suo errore invece di sparire in silenzio.
   *  recent_for_project ordina per updated_at desc: il primo match è il più recente. */
  const lastJob = (kind: Job["kind"]): Job | null => {
    const found = (progress?.jobs ?? []).find(j => j.kind === kind);
    return found ?? null;
  };

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        const data = await getProject(projectId);
        setProject(data);
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
    try {
      setProject(await getProject(projectId));
    } catch {
      // UploadZone mostra gia' il proprio errore; qui basta non rompere lo state
    }
  }, [projectId]);

  /** Riordino ottimistico: aggiorna subito la UI, conferma dal server, rollback in caso di errore. */
  const handleReorder = useCallback(async (mediaIds: string[]) => {
    const prev = project;
    if (!prev) return;
    const byId = new Map(prev.media.map(m => [m.id, m]));
    setProject({
      ...prev,
      media: mediaIds.map((id, i) => ({ ...byId.get(id)!, order_index: i })),
    });
    setTimelineBusy(true);
    try {
      setProject(await reorderMedia(projectId, mediaIds));
    } catch (err) {
      setProject(prev);
      throw err;
    } finally {
      setTimelineBusy(false);
    }
  }, [project, projectId]);

  const handleToggleFill = useCallback(async (mediaId: string, fill: BackgroundFill) => {
    setTimelineBusy(true);
    try {
      setProject(await updateMediaFill(projectId, mediaId, fill));
    } finally {
      setTimelineBusy(false);
    }
  }, [projectId]);

  const handleSettings = useCallback(async (patch: SettingsPatch) => {
    setSettingsBusy(true);
    try {
      setProject(await updateSettings(projectId, patch));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Salvataggio impostazioni fallito");
    } finally {
      setSettingsBusy(false);
    }
  }, [projectId]);

  const handleAudioUpload = useCallback(async (file: File) => {
    setAudioBusy(true);
    try {
      setProject(await uploadAudio(projectId, file));
    } finally {
      setAudioBusy(false);
    }
  }, [projectId]);

  const handleGenerateEdit = useCallback(async () => {
    setEditBusy(true);
    try {
      setProject(await planEdit(projectId));
    } finally {
      setEditBusy(false);
    }
  }, [projectId]);

  /** Ritocco manuale di una clip: il server ricompila il piano, qui aggiorniamo lo state. */
  const handlePatchClip = useCallback(async (mediaId: string, patch: ClipOverride) => {
    setEditBusy(true);
    try {
      setProject(await patchClipOverride(projectId, mediaId, patch));
    } finally {
      setEditBusy(false);
    }
  }, [projectId]);

  const handleResetClip = useCallback(async (mediaId: string) => {
    setEditBusy(true);
    try {
      setProject(await resetClipOverride(projectId, mediaId));
    } finally {
      setEditBusy(false);
    }
  }, [projectId]);

  // Submit in background (coda job): il completamento arriva via SSE + sync.
  const handleSubmitRender = useCallback(
    () => submitRenderJob(projectId),
    [projectId],
  );

  const handleSubmitDriveImport = useCallback(
    (fileIds: string[], folderIds: string[]) =>
      submitDriveImportJob(projectId, fileIds, folderIds),
    [projectId],
  );

  const handleClearErrors = useCallback(async () => {
    setClearBusy(true);
    try {
      setProject(await clearErrors(projectId));
    } finally {
      setClearBusy(false);
    }
  }, [projectId]);

  // Sync realtime (M8): se lo state remoto cambia (SSE), ricarica throttled.
  useEffect(() => {
    if (!progress || !project || syncingRef.current) return;
    if (progress.updated_at <= project.updated_at) return;
    if (Date.now() - lastSyncRef.current < 3000) return;
    lastSyncRef.current = Date.now();
    syncingRef.current = true;
    getProject(projectId)
      .then(setProject)
      .catch(() => null)
      .finally(() => {
        syncingRef.current = false;
      });
  }, [progress, project, projectId]);

  if (loading) {
    return (
      <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-8 px-6">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-emerald-400 border-t-transparent" />
        <p className="text-slate-400">Caricamento progetto&hellip;</p>
      </main>
    );
  }

  if (error && !project) {
    return (
      <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-rose-400">{error}</p>
        <button
          onClick={() => router.push("/")}
          className="text-emerald-400 hover:underline"
        >
          Torna alla home
        </button>
      </main>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 px-6 py-12">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Progetto {project?.project_id?.slice(0, 8)}</h1>
          <p className="text-sm text-slate-400">
            {project?.media.length || 0} file caricati
          </p>
        </div>
        <span className="text-xs px-2 py-1 rounded bg-emerald-900/40 border border-emerald-800 text-emerald-300">
          ✓ Pronto
        </span>
      </div>

      {progress && <PipelineProgress log={progress.pipeline_log} />}

      {project && (
        <DriveSection
          projectId={projectId}
          onSubmitImport={handleSubmitDriveImport}
          job={lastJob("drive_import")}
        />
      )}

      {project && (
        <ExportSection project={project} onSubmit={handleSubmitRender} job={lastJob("render")} />
      )}

      {project && (
        <MontageSection
          project={project}
          onGenerate={handleGenerateEdit}
          onPatchClip={handlePatchClip}
          onResetClip={handleResetClip}
          busy={editBusy}
        />
      )}

      {project && (
        <AudioSection audio={project.audio} onUpload={handleAudioUpload} busy={audioBusy} />
      )}

      {project && (
        <ProjectSettings
          spec={project.output_spec}
          onSave={handleSettings}
          busy={settingsBusy}
          media={project.media}
        />
      )}

      <UploadZone projectId={projectId} onUploadComplete={handleUploadComplete} />

      {project && (
        <Timeline
          projectId={projectId}
          media={project.media}
          onReorder={handleReorder}
          onToggleFill={handleToggleFill}
          busy={timelineBusy}
        />
      )}

      {error && (
        <p className="rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">
          {error}
        </p>
      )}

      {project && (
        <ErrorPanel errors={project.errors} onClear={handleClearErrors} busy={clearBusy} />
      )}
    </main>
  );
}
