export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export interface HealthResponse {
  status: string;
  service: string;
  projects_count: number;
}

export interface ProjectSummary {
  project_id: string;
  media_count: number;
  has_audio: boolean;
  has_render: boolean;
  updated_at?: number;
}

export type Orientation = "landscape" | "portrait" | "square";
export type FitMode = "cover" | "contain";
export type BackgroundFill = "blur" | "solid_color";
export type MediaType = "photo" | "video";
export type MediaSource = "local" | "google_drive";

export interface MediaItem {
  id: string;
  source: MediaSource;
  drive_file_id?: string;
  path: string;
  type: MediaType;
  orientation: Orientation;
  width: number;
  height: number;
  duration_sec: number;
  order_index: number;
  fit_mode?: FitMode;
  background_fill?: BackgroundFill;
  trim_start_sec?: number;
  trim_end_sec?: number;
  source_fps?: number;
}

export interface AudioTrack {
  path?: string;
  duration_sec: number;
  bpm: number;
  beat_markers_sec: number[];
  energy_curve: number[];
}

export type AudioInfo = AudioTrack;

export interface OutputSpec {
  resolution: string;
  fps: number;
  background_fill: BackgroundFill;
  vcodec: "h264" | "h265";
}

export interface KenBurnsParams {
  movement: string;
  params: Record<string, unknown>;
}

export interface EditEntry {
  media_id: string;
  duration_sec: number;
  transition_out: number;
  start_sec_in_final_video: number;
  ken_burns?: KenBurnsParams;
}

export interface ClipOverride {
  duration_sec?: number;
  transition_out?: number;
  ken_burns_movement?: string;
}

export interface JobProgress {
  fraction: number;
  label?: string;
  note?: string;
}

export interface Job {
  id: string;
  kind: "render" | "drive_import" | "intake";
  status: "pending" | "running" | "completed" | "failed";
  error?: string;
  created_at: string;
  updated_at: string;
  progress?: JobProgress;
}

export interface PipelineLogEntry {
  stage: string;
  status: "pending" | "running" | "completed" | "failed";
  message?: string;
  timestamp?: number;
}

export interface RenderManifestOutput {
  path: string;
  resolution?: string;
  fps?: number;
  vcodec?: string;
  preset?: string;
  crf?: number;
  audio_codec?: string | null;
  size_bytes?: number;
  duration_sec?: number;
}

export interface RenderManifest {
  version?: number;
  status?: "done" | "failed" | "running";
  output?: RenderManifestOutput;
  inputs?: Record<string, unknown>[];
  segments?: Record<string, unknown>[];
  transitions?: Record<string, unknown>[];
  filter_complex?: string;
  args?: string[];
  total_sec?: number;
  audio?: Record<string, unknown>;
}

export interface QAReport {
  status: "approved" | "rejected";
  checks?: { name: string; passed: boolean; detail: string }[];
  issues?: { check: string; message: string; route_to: string }[];
}

export interface ProjectError {
  stage: string;
  message: string;
  detail?: string;
}

export interface ProjectState {
  schema_version: number;
  project_id: string;
  media: MediaItem[];
  audio: AudioTrack;
  style_profile: string;
  output_spec: OutputSpec;
  edit_decision_list: EditEntry[];
  clip_overrides: Record<string, ClipOverride>;
  render_manifest?: RenderManifest;
  qa_report?: QAReport;
  errors: ProjectError[];
  pipeline_log: PipelineLogEntry[];
  created_at: number;
  updated_at: number;
}

export interface ProgressSnapshot {
  jobs: Job[];
  pipeline_log: PipelineLogEntry[];
  updated_at: number;
  errors_count: number;
  media_count: number;
  has_audio: boolean;
  has_edit: boolean;
  has_render: boolean;
  qa_status?: string;
}

export interface SettingsPatch {
  background_fill?: BackgroundFill;
  resolution?: string;
  fps?: number;
  vcodec?: "h264" | "h265";
}

export const API_BASE_VALUE = API_BASE;

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120000); // 2 minuti per upload grandi

  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        ...(options?.headers || {}),
        "Content-Type": "application/json",
      },
    });

    clearTimeout(timeoutId);

    if (!res.ok) {
      const err = await res.text();
      throw new Error(err || `HTTP ${res.status}`);
    }

    return res.json();
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error("Timeout della richiesta: il server non ha risposto entro 2 minuti");
    }
    throw err;
  }
}

export async function getHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>(`${API_BASE}/health`);
}

export async function createProject(): Promise<ProjectState> {
  return fetchJson<ProjectState>(`${API_BASE}/projects`, {
    method: "POST",
  });
}

export async function listProjects(): Promise<ProjectSummary[]> {
  return fetchJson<ProjectSummary[]>(`${API_BASE}/projects`);
}

export async function deleteProject(projectId: string): Promise<void> {
  await fetch(`${API_BASE}/projects/${projectId}`, {
    method: "DELETE",
  });
}

export async function getProject(projectId: string): Promise<ProjectState> {
  return fetchJson<ProjectState>(`${API_BASE}/projects/${projectId}`);
}

export async function uploadMedia(
  projectId: string,
  files: File[]
): Promise<ProjectState> {
  const formData = new FormData();
  files.forEach((f) => formData.append("files", f));

  // NON impostare Content-Type manualmente: il browser lo gestisce con boundary corretto
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 300000); // 5 minuti per upload multipli/grandi

  try {
    const res = await fetch(`${API_BASE}/projects/${projectId}/media`, {
      method: "POST",
      signal: controller.signal,
      body: formData,
      // Importante: NON aggiungere headers Content-Type per FormData
      // Il browser imposta automaticamente "multipart/form-data; boundary=..."
    });

    clearTimeout(timeoutId);

    if (!res.ok) {
      const errText = await res.text();
      
      // Gestione errori specifici HTTP
      if (res.status === 413) {
        throw new Error("File troppo grande: il limite è 500MB per file");
      }
      if (res.status === 400) {
        throw new Error(`Formato non supportato: ${errText || "contenuto non valido"}`);
      }
      if (res.status === 404) {
        throw new Error("Progetto non trovato");
      }
      if (res.status === 500) {
        throw new Error(`Errore interno del server: ${errText}`);
      }
      
      throw new Error(errText || `HTTP ${res.status}`);
    }

    const data = await res.json();
    
    // Validazione response: deve essere un ProjectState valido
    if (!data || typeof data !== "object" || !data.project_id || !Array.isArray(data.media)) {
      throw new Error("Response dal server non valida");
    }
    
    return data;
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error("Upload scaduto: il file è molto grande o la connessione è lenta. Riprova con meno file per volta.");
    }
    // Rilancia gli errori già formattati
    if (err instanceof Error) {
      throw err;
    }
    throw new Error("Errore sconosciuto durante l'upload");
  }
}

export async function reorderMedia(
  projectId: string,
  mediaIds: string[]
): Promise<ProjectState> {
  return fetchJson<ProjectState>(`${API_BASE}/projects/${projectId}/media/order`, {
    method: "PUT",
    body: JSON.stringify({ media_ids: mediaIds }),
  });
}

export async function updateMediaFill(
  projectId: string,
  mediaId: string,
  fill: BackgroundFill
): Promise<ProjectState> {
  return fetchJson<ProjectState>(
    `${API_BASE}/projects/${projectId}/media/${mediaId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ background_fill: fill }),
    }
  );
}

export async function updateSettings(
  projectId: string,
  patch: SettingsPatch
): Promise<ProjectState> {
  return fetchJson<ProjectState>(`${API_BASE}/projects/${projectId}/settings`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function uploadAudio(
  projectId: string,
  file: File
): Promise<ProjectState> {
  const formData = new FormData();
  formData.append("file", file);

  // NON impostare Content-Type manualmente per FormData
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 300000); // 5 minuti

  try {
    const res = await fetch(`${API_BASE}/projects/${projectId}/audio`, {
      method: "POST",
      signal: controller.signal,
      body: formData,
    });

    clearTimeout(timeoutId);

    if (!res.ok) {
      const errText = await res.text();
      
      if (res.status === 413) {
        throw new Error("File audio troppo grande: il limite è 500MB");
      }
      if (res.status === 400) {
        throw new Error(`Formato audio non supportato: ${errText || "contenuto non valido"}`);
      }
      if (res.status === 404) {
        throw new Error("Progetto non trovato");
      }
      
      throw new Error(errText || `HTTP ${res.status}`);
    }

    const data = await res.json();
    
    if (!data || typeof data !== "object" || !data.project_id) {
      throw new Error("Response dal server non valida");
    }
    
    return data;
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error("Upload audio scaduto: riprova con un file più piccolo");
    }
    if (err instanceof Error) {
      throw err;
    }
    throw new Error("Errore sconosciuto durante l'upload audio");
  }
}

export async function planEdit(projectId: string): Promise<ProjectState> {
  return fetchJson<ProjectState>(`${API_BASE}/projects/${projectId}/edit`, {
    method: "POST",
  });
}

export async function patchClipOverride(
  projectId: string,
  mediaId: string,
  patch: ClipOverride
): Promise<ProjectState> {
  return fetchJson<ProjectState>(
    `${API_BASE}/projects/${projectId}/edit/clips/${mediaId}`,
    {
      method: "PATCH",
      body: JSON.stringify(patch),
    }
  );
}

export async function resetClipOverride(
  projectId: string,
  mediaId: string
): Promise<ProjectState> {
  return fetchJson<ProjectState>(
    `${API_BASE}/projects/${projectId}/edit/clips/${mediaId}`,
    {
      method: "DELETE",
    }
  );
}

export async function submitRenderJob(projectId: string): Promise<ProjectState> {
  return fetchJson<ProjectState>(`${API_BASE}/projects/${projectId}/render`, {
    method: "POST",
  });
}

export async function submitDriveImportJob(
  projectId: string,
  fileIds: string[],
  folderIds: string[],
  background: boolean = false
): Promise<ProjectState | { job: Job }> {
  const url = new URL(`${API_BASE}/projects/${projectId}/drive/import`);
  if (background) {
    url.searchParams.set("background", "true");
  }
  const res = await fetch(url.toString(), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ file_ids: fileIds, folder_ids: folderIds }),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }

  // Se background=true, il backend ritorna 202 con {job: ...}
  // Altrimenti ritorna ProjectState completo
  return res.json();
}

export async function clearErrors(projectId: string): Promise<ProjectState> {
  return fetchJson<ProjectState>(`${API_BASE}/projects/${projectId}/errors/clear`, {
    method: "POST",
  });
}

export function getEventSourceUrl(projectId: string): string {
  return `${API_BASE}/projects/${projectId}/events`;
}

export interface DriveEntry {
  id: string;
  name: string;
  mimeType: string;
  is_folder: boolean;
}

export interface DriveStatus {
  configured: boolean;
  connected: boolean;
  email?: string;
}

export async function driveAuthUrl(): Promise<string> {
  const data = await fetchJson<{ auth_url: string }>(`${API_BASE}/drive/auth-url`);
  return data.auth_url;
}

export async function saveDriveCredentials(clientId: string, clientSecret: string): Promise<void> {
  await fetch(`${API_BASE}/drive/credentials`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
  });
}

export async function driveStatus(): Promise<DriveStatus> {
  return fetchJson<DriveStatus>(`${API_BASE}/drive/status`);
}

export async function driveDisconnect(): Promise<void> {
  await fetch(`${API_BASE}/drive/disconnect`, {
    method: "POST",
  });
}

export async function driveListFiles(
  projectId: string,
  folderId?: string
): Promise<{ current: { id: string; name: string }; entries: DriveEntry[] }> {
  const url = new URL(`${API_BASE}/projects/${projectId}/drive/files`);
  if (folderId) url.searchParams.set("folder_id", folderId);
  return fetchJson<{ current: { id: string; name: string }; entries: DriveEntry[] }>(url.toString());
}

export function isJobActive(job?: Job | null): boolean {
  if (!job) return false;
  return job.status === "pending" || job.status === "running";
}

export function mediaThumbUrl(projectId: string, mediaId: string): string {
  return `${API_BASE}/projects/${projectId}/media/${mediaId}/thumb`;
}

export const CLIP_MOVEMENTS = [
  { value: "static", label: "Fisso" },
  { value: "pan_left", label: "Pan sinistra" },
  { value: "pan_right", label: "Pan destra" },
  { value: "zoom_in_slow", label: "Zoom in" },
  { value: "zoom_out_slow", label: "Zoom out" },
  { value: "pan_and_zoom_diag", label: "Diagonale" },
] as const;

export function downloadUrl(projectId: string): string {
  return `${API_BASE}/projects/${projectId}/download`;
}
