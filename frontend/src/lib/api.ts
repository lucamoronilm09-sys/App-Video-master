/**
 * API Layer per il frontend
 * 
 * Configurazione tramite environment variables:
 * - NEXT_PUBLIC_API_URL: URL base dell'API (default: "/api" per proxy Next.js)
 * - NEXT_PUBLIC_API_TIMEOUT_MS: Timeout per le richieste in ms (default: 120000)
 * - NEXT_PUBLIC_UPLOAD_TIMEOUT_MS: Timeout per gli upload in ms (default: 300000)
 */

// ============================================================================
// CONFIGURAZIONE
// ============================================================================

/** URL base per le chiamate API (usa il proxy Next.js di default) */
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

/** URL diretto per upload di file grandi (bypassa il proxy) */
const DIRECT_API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Timeout per richieste standard (2 minuti) */
const DEFAULT_TIMEOUT_MS = Number(process.env.NEXT_PUBLIC_API_TIMEOUT_MS) || 120000;

/** Timeout per upload di file (5 minuti) */
const UPLOAD_TIMEOUT_MS = Number(process.env.NEXT_PUBLIC_UPLOAD_TIMEOUT_MS) || 300000;

// ============================================================================
// TIPI - Contratto API Backend
// ============================================================================

export interface HealthResponse {
  status: string;
  service: string;
  projects_count: number;
}

export interface ProjectSummary {
  project_id: string;
  name?: string;
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
  face_count?: number;
  people_count?: number;
  importance_score?: number;
  vision_ai_used?: boolean;
  scene_type?: string;
  ai_duration_sec?: number;
  ai_edit_score?: number;
  music_sync?: boolean;
}

export interface AudioTrack {
  id?: string;
  name?: string;
  path?: string;
  duration_sec: number;
  bpm: number;
  beat_times_sec?: number[];
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
  resolution: string;
  fps: number;
  vcodec: "libx264" | "libx265";
  preset: string;
  crf: number;
  duration_sec?: number;
  size_bytes?: number;
  rendered_at?: number;
}

export interface InputEntry {
  index: number;
  path: string;
  kind: "video" | "photo" | "audio";
  audio_track?: number;
}

export interface SegmentEntry {
  media_id: string;
  input_index: number;
  kind: "video" | "photo";
  fit: "cover" | "contain";
  label: string;
  filter: string;
  duration_sec: number;
}

export interface TransitionEntry {
  index: number;
  from_segment: number;
  to_segment: number;
  duration_sec: number;
  offset_sec: number;
  cut: boolean;
}

export interface AudioTrackInfo {
  path?: string;
  name?: string;
  duration_sec: number;
}

export interface AudioBlock {
  tracks: AudioTrackInfo[];
}

export interface ValidationReport {
  codec: string;
  width: number;
  height: number;
  duration: number;
  size_bytes: number;
}

export interface RenderManifest {
  version: number;
  status: "ready" | "running" | "done" | "failed";
  inputs: InputEntry[];
  segments: SegmentEntry[];
  transitions: TransitionEntry[];
  filter_complex?: string;
  filter_complex_script: string;
  args: string[];
  total_sec: number;
  output: RenderManifestOutput;
  audio?: AudioBlock;
  fps: number;
  resolution: string;
  vcodec: string;
  source_video_audio: "muted" | "mixed";
  validation?: ValidationReport | null;
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

export interface StoryChapter {
  title: string;
  kind: string;
  media_ids: string[];
  start_index: number;
  end_index: number;
  reason?: string;
}

export interface MusicStructure {
  duration_sec?: number;
  bpm?: number;
  energy?: string;
  sections?: { start_sec: number; end_sec: number; label: string; energy: number }[];
  climax_sec?: number;
  peak_energy?: number;
}

export interface AIFeedback {
  rating: "up" | "down";
  reasons: string[];
  note: string;
  created_at: number;
}

export interface ProjectState {
  schema_version: number;
  project_id: string;
  name: string;
  user_prompt: string;
  media: MediaItem[];
  audio: AudioTrack;
  audio_tracks?: AudioTrack[];
  style_profile: string;
  output_spec: OutputSpec;
  edit_decision_list: EditEntry[];
  story_chapters: StoryChapter[];
  music_structure: MusicStructure;
  clip_overrides: Record<string, ClipOverride>;
  ai_feedback?: AIFeedback | null;
  ai_feedback_history?: AIFeedback[];
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

export interface ProjectPatch {
  name?: string;
  user_prompt?: string;
  style_profile?: string;
}

export interface FeedbackRequest {
  rating: "up" | "down";
  reasons?: string[];
  note?: string;
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

// ============================================================================
// ERRORI CUSTOM
// ============================================================================

/** Errore di timeout */
export class ApiTimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiTimeoutError";
  }
}

/** Errore HTTP con status code */
export class ApiHttpError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly statusText: string
  ) {
    super(message);
    this.name = "ApiHttpError";
  }
}

/** Errore di rete */
export class ApiNetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiNetworkError";
  }
}

// ============================================================================
// FUNZIONI DI SUPPORTO
// ============================================================================

/**
 * Esegue una fetch con timeout e gestione errori centralizzata
 */
async function fetchWithTimeout(
  url: string,
  options: RequestInit & { timeoutMs?: number } = {}
): Promise<Response> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(fetchOptions.headers ?? {}),
      },
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof Error && error.name === "AbortError") {
      throw new ApiTimeoutError(`Timeout dopo ${timeoutMs}ms`);
    }
    if (error instanceof TypeError && error.message.includes("fetch")) {
      throw new ApiNetworkError("Errore di rete: impossibile raggiungere il server");
    }
    throw error;
  }
}

/**
 * Esegue una fetch JSON con gestione errori centralizzata
 */
async function fetchJson<T>(
  url: string,
  options?: RequestInit & { timeoutMs?: number }
): Promise<T> {
  const response = await fetchWithTimeout(url, options);

  if (!response.ok) {
    const errorBody = await response.text().catch(() => "");
    throw new ApiHttpError(
      errorBody || `HTTP ${response.status}: ${response.statusText}`,
      response.status,
      response.statusText
    );
  }

  // Gestione caso 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

/**
 * Crea FormData da una lista di File
 */
function createFormData(files: File[], fieldName: string = "files"): FormData {
  const formData = new FormData();
  files.forEach((file) => formData.append(fieldName, file));
  return formData;
}

// ============================================================================
// API - PROGETTI
// ============================================================================

/** Ottiene lo stato di salute del backend */
export async function getHealth(): Promise<HealthResponse> {
  return fetchJson(`${API_BASE}/health`);
}

/** Crea un nuovo progetto vuoto */
export async function createProject(): Promise<ProjectState> {
  return fetchJson(`${API_BASE}/projects`, { method: "POST" });
}

/** Lista tutti i progetti */
export async function listProjects(): Promise<ProjectSummary[]> {
  return fetchJson(`${API_BASE}/projects`);
}

/** Elimina un progetto */
export async function deleteProject(projectId: string): Promise<void> {
  const response = await fetchWithTimeout(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    const errorBody = await response.text().catch(() => "");
    throw new ApiHttpError(errorBody || `HTTP ${response.status}`, response.status, response.statusText);
  }
}

/** Ottiene i dettagli di un progetto */
export async function getProject(projectId: string): Promise<ProjectState> {
  return fetchJson(`${API_BASE}/projects/${projectId}`);
}

/** Aggiorna un progetto (patch parziale) */
export async function updateProject(
  projectId: string,
  patch: ProjectPatch
): Promise<ProjectState> {
  return fetchJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

/** Duplica un progetto esistente */
export async function duplicateProject(projectId: string): Promise<ProjectState> {
  return fetchJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}/duplicate`, {
    method: "POST",
  });
}

/** Invia feedback AI su un progetto */
export async function submitFeedback(
  projectId: string,
  feedback: FeedbackRequest
): Promise<ProjectState> {
  return fetchJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}/feedback`, {
    method: "POST",
    body: JSON.stringify(feedback),
  });
}

// ============================================================================
// API - MEDIA
// ============================================================================

/** Carica file multimediali in un progetto */
export async function uploadMedia(
  projectId: string,
  files: File[]
): Promise<ProjectState> {
  const formData = createFormData(files);
  const response = await fetchWithTimeout(
    `${DIRECT_API_BASE}/api/projects/${projectId}/media`,
    {
      method: "POST",
      body: formData,
      timeoutMs: UPLOAD_TIMEOUT_MS,
      headers: {}, // Rimuovi Content-Type per FormData
    }
  );

  if (!response.ok) {
    const errorBody = await response.text().catch(() => "");
    throw new ApiHttpError(errorBody || `HTTP ${response.status}`, response.status, response.statusText);
  }

  return response.json();
}

/** Riordina i media di un progetto */
export async function reorderMedia(
  projectId: string,
  mediaIds: string[]
): Promise<ProjectState> {
  return fetchJson(`${API_BASE}/projects/${projectId}/media/order`, {
    method: "PUT",
    body: JSON.stringify({ media_ids: mediaIds }),
  });
}

/** Aggiorna il fill mode di un media */
export async function updateMediaFill(
  projectId: string,
  mediaId: string,
  fill: BackgroundFill
): Promise<ProjectState> {
  return fetchJson(`${API_BASE}/projects/${projectId}/media/${mediaId}`, {
    method: "PATCH",
    body: JSON.stringify({ background_fill: fill }),
  });
}

/** Ottiene URL per la thumbnail di un media */
export function mediaThumbUrl(projectId: string, mediaId: string): string {
  return `${API_BASE}/projects/${projectId}/media/${mediaId}/thumb`;
}

// ============================================================================
// API - AUDIO
// ============================================================================

/** Carica file audio in un progetto */
export async function uploadAudio(
  projectId: string,
  file: File
): Promise<ProjectState> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetchWithTimeout(
    `${DIRECT_API_BASE}/api/projects/${projectId}/audio`,
    {
      method: "POST",
      body: formData,
      timeoutMs: UPLOAD_TIMEOUT_MS,
      headers: {}, // Rimuovi Content-Type per FormData
    }
  );

  if (!response.ok) {
    const errorBody = await response.text().catch(() => "");
    throw new ApiHttpError(errorBody || `HTTP ${response.status}`, response.status, response.statusText);
  }

  return response.json();
}

// ============================================================================
// API - EDITING
// ============================================================================

/** Pianifica l'editing automatico del progetto */
export async function planEdit(projectId: string): Promise<ProjectState> {
  return fetchJson(`${API_BASE}/projects/${projectId}/edit`, { method: "POST" });
}

/** Aggiorna override per un clip */
export async function patchClipOverride(
  projectId: string,
  mediaId: string,
  patch: ClipOverride
): Promise<ProjectState> {
  return fetchJson(`${API_BASE}/projects/${projectId}/edit/clips/${mediaId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

/** Resetta override per un clip */
export async function resetClipOverride(
  projectId: string,
  mediaId: string
): Promise<ProjectState> {
  return fetchJson(`${API_BASE}/projects/${projectId}/edit/clips/${mediaId}`, {
    method: "DELETE",
  });
}

// ============================================================================
// API - RENDER
// ============================================================================

/** Avvia il rendering del progetto */
export async function submitRenderJob(
  projectId: string
): Promise<ProjectState | { job: Job }> {
  const response = await fetchWithTimeout(
    `${API_BASE}/projects/${projectId}/render?background=true`,
    { method: "POST" }
  );

  if (!response.ok) {
    const errorBody = await response.text().catch(() => "");
    throw new ApiHttpError(errorBody || `HTTP ${response.status}`, response.status, response.statusText);
  }

  return response.json();
}

/** Aggiorna le impostazioni di output del progetto */
export async function updateSettings(
  projectId: string,
  patch: SettingsPatch
): Promise<ProjectState> {
  return fetchJson(`${API_BASE}/projects/${projectId}/settings`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

// ============================================================================
// API - GOOGLE DRIVE
// ============================================================================

/** Ottiene URL per autenticazione Google Drive */
export async function driveAuthUrl(): Promise<string> {
  const result = await fetchJson<{ url: string }>(`${API_BASE}/drive/auth-url`);
  return result.url;
}

/** Salva le credenziali Google Drive */
export async function saveDriveCredentials(
  clientId: string,
  clientSecret: string
): Promise<void> {
  const response = await fetchWithTimeout(`${API_BASE}/drive/credentials`, {
    method: "POST",
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
  });

  if (!response.ok) {
    const errorBody = await response.text().catch(() => "");
    throw new ApiHttpError(errorBody || `HTTP ${response.status}`, response.status, response.statusText);
  }
}

/** Ottiene lo stato della connessione Google Drive */
export async function driveStatus(): Promise<DriveStatus> {
  return fetchJson(`${API_BASE}/drive/status`);
}

/** Disconnette Google Drive */
export async function driveDisconnect(): Promise<void> {
  const response = await fetchWithTimeout(`${API_BASE}/drive/disconnect`, {
    method: "POST",
  });

  if (!response.ok) {
    const errorBody = await response.text().catch(() => "");
    throw new ApiHttpError(errorBody || `HTTP ${response.status}`, response.status, response.statusText);
  }
}

/** Lista file/cartelle da Google Drive */
export async function driveListFiles(
  projectId: string,
  options?: {
    folderId?: string;
    pageToken?: string;
    shared?: boolean;
  }
): Promise<{
  current: { id: string; name: string };
  entries: DriveEntry[];
  nextPageToken?: string;
}> {
  const params = new URLSearchParams();
  if (options?.folderId) params.set("folder_id", options.folderId);
  if (options?.pageToken) params.set("page_token", options.pageToken);
  if (options?.shared) params.set("shared", "true");

  const queryString = params.toString();
  const url = `${API_BASE}/projects/${projectId}/drive/files${queryString ? `?${queryString}` : ""}`;

  return fetchJson(url);
}

/** Importa file/folder da Google Drive nel progetto */
export async function submitDriveImportJob(
  projectId: string,
  fileIds: string[],
  folderIds: string[],
  background: boolean = true
): Promise<ProjectState | { job: Job }> {
  const queryParams = background ? "?background=true" : "";
  const response = await fetchWithTimeout(
    `${API_BASE}/projects/${projectId}/drive/import${queryParams}`,
    {
      method: "POST",
      body: JSON.stringify({ file_ids: fileIds, folder_ids: folderIds }),
    }
  );

  if (!response.ok) {
    const errorBody = await response.text().catch(() => "");
    throw new ApiHttpError(errorBody || `HTTP ${response.status}`, response.status, response.statusText);
  }

  return response.json();
}

// ============================================================================
// API - ERROR HANDLING
// ============================================================================

/** Pulisce gli errori di un progetto */
export async function clearErrors(projectId: string): Promise<ProjectState> {
  return fetchJson(`${API_BASE}/projects/${projectId}/errors/clear`, {
    method: "POST",
  });
}

// ============================================================================
// UTILITIES
// ============================================================================

/** Ottiene URL per Server-Sent Events */
export function getEventSourceUrl(projectId: string): string {
  return `${API_BASE}/projects/${projectId}/events`;
}

/** Controlla se un job è attivo (pending o running) */
export function isJobActive(job?: Job | null): boolean {
  return !!job && (job.status === "pending" || job.status === "running");
}

/** Movimenti Ken Burns disponibili */
export const CLIP_MOVEMENTS = [
  { value: "static", label: "Fisso" },
  { value: "pan_left", label: "Pan sinistra" },
  { value: "pan_right", label: "Pan destra" },
  { value: "zoom_in_slow", label: "Zoom in" },
  { value: "zoom_out_slow", label: "Zoom out" },
  { value: "pan_and_zoom_diag", label: "Diagonale" },
] as const;

/** Ottiene URL per download del progetto renderizzato */
export function downloadUrl(projectId: string): string {
  return `${API_BASE}/projects/${projectId}/download`;
}

/** Valore costante per compatibilità */
export const API_BASE_VALUE = API_BASE;
