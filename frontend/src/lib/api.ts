export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface HealthResponse {
  service: string;
  projects_count: number;
}

export interface ProjectSummary {
  project_id: string;
  media_count: number;
  has_audio: boolean;
  has_render: boolean;
}

export interface MediaItem {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  order_index: number;
  duration_seconds?: number;
  is_video: boolean;
  fill_mode: "cover" | "contain";
}

export interface AudioTrack {
  id: string;
  filename: string;
  duration_seconds: number;
}

export type AudioInfo = AudioTrack;

export interface OutputSpec {
  resolution: string;
  fps: number;
  transition_duration: number;
}

export interface ClipOverride {
  start_time?: number;
  end_time?: number;
  zoom?: number;
}

export interface Job {
  id: string;
  kind: "render" | "drive_import" | "intake";
  status: "pending" | "running" | "completed" | "failed";
  error?: string;
  created_at: string;
  updated_at: string;
}

export interface PipelineLogEntry {
  step: string;
  status: "pending" | "running" | "completed" | "failed";
  message?: string;
}

export interface ProjectState {
  project_id: string;
  media: MediaItem[];
  audio?: AudioTrack;
  output_spec: OutputSpec;
  clips?: ClipOverride[];
  errors: { title: string; detail: string; hint?: string }[];
  updated_at: number;
}

export interface ProgressState {
  jobs: Job[];
  pipeline_log: PipelineLogEntry[];
  updated_at: number;
}

export interface SettingsPatch {
  resolution?: string;
  fps?: number;
  transition_duration?: number;
}

export const API_BASE_VALUE = API_BASE;
export type BackgroundFill = "cover" | "contain";

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...options,
    headers: {
      ...(options?.headers || {}),
      "Content-Type": "application/json",
    },
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }

  return res.json();
}

export async function getHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>(`${API_BASE}/health`);
}

export async function createProject(): Promise<{ project_id: string }> {
  return fetchJson<{ project_id: string }>(`${API_BASE}/projects`, {
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
): Promise<{ uploaded: number }> {
  const formData = new FormData();
  files.forEach((f) => formData.append("files", f));

  const res = await fetch(`${API_BASE}/projects/${projectId}/media`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }

  return res.json();
}

export async function reorderMedia(
  projectId: string,
  mediaIds: string[]
): Promise<ProjectState> {
  return fetchJson<ProjectState>(`${API_BASE}/projects/${projectId}/media/reorder`, {
    method: "PATCH",
    body: JSON.stringify({ media_ids: mediaIds }),
  });
}

export async function updateMediaFill(
  projectId: string,
  mediaId: string,
  fill: BackgroundFill
): Promise<ProjectState> {
  return fetchJson<ProjectState>(
    `${API_BASE}/projects/${projectId}/media/${mediaId}/fill`,
    {
      method: "PATCH",
      body: JSON.stringify({ fill_mode: fill }),
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

  const res = await fetch(`${API_BASE}/projects/${projectId}/audio`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }

  return res.json();
}

export async function planEdit(projectId: string): Promise<ProjectState> {
  return fetchJson<ProjectState>(`${API_BASE}/projects/${projectId}/plan`, {
    method: "POST",
  });
}

export async function patchClipOverride(
  projectId: string,
  mediaId: string,
  patch: ClipOverride
): Promise<ProjectState> {
  return fetchJson<ProjectState>(
    `${API_BASE}/projects/${projectId}/clips/${mediaId}`,
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
    `${API_BASE}/projects/${projectId}/clips/${mediaId}/reset`,
    {
      method: "POST",
    }
  );
}

export async function submitRenderJob(projectId: string): Promise<Job> {
  return fetchJson<Job>(`${API_BASE}/projects/${projectId}/render`, {
    method: "POST",
  });
}

export async function submitDriveImportJob(
  projectId: string,
  fileIds: string[],
  folderIds: string[]
): Promise<Job> {
  return fetchJson<Job>(
    `${API_BASE}/projects/${projectId}/drive/import`,
    {
      method: "POST",
      body: JSON.stringify({ file_ids: fileIds, folder_ids: folderIds }),
    }
  );
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
  connected: boolean;
  email?: string;
}

export async function driveAuthUrl(): Promise<{ auth_url: string }> {
  return fetchJson<{ auth_url: string }>(`${API_BASE}/drive/auth-url`);
}

export async function saveDriveCredentials(projectId: string, code: string): Promise<void> {
  await fetch(`${API_BASE}/projects/${projectId}/drive/callback`, {
    method: "POST",
    body: JSON.stringify({ code }),
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
  q?: string
): Promise<{ files: DriveEntry[] }> {
  const url = new URL(`${API_BASE}/projects/${projectId}/drive/files`);
  if (q) url.searchParams.set("q", q);
  return fetchJson<{ files: DriveEntry[] }>(url.toString());
}

export function isJobActive(job?: Job | null): boolean {
  if (!job) return false;
  return job.status === "pending" || job.status === "running";
}

export function mediaThumbUrl(projectId: string, mediaId: string): string {
  return `${API_BASE}/projects/${projectId}/media/${mediaId}/thumb`;
}

export const CLIP_MOVEMENTS = [
  { value: "none", label: "Fisso" },
  { value: "zoom-in", label: "Zoom in" },
  { value: "zoom-out", label: "Zoom out" },
  { value: "pan-left", label: "Pan sinistra" },
  { value: "pan-right", label: "Pan destra" },
] as const;

export function downloadUrl(projectId: string): string {
  return `${API_BASE}/projects/${projectId}/render/download`;
}
