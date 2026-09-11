export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

export interface HealthResponse { status: string; service: string; projects_count: number; }
export interface ProjectSummary { project_id: string; name?: string; media_count: number; has_audio: boolean; has_render: boolean; updated_at?: number; }
export type Orientation = "landscape" | "portrait" | "square";
export type FitMode = "cover" | "contain";
export type BackgroundFill = "blur" | "solid_color";
export type MediaType = "photo" | "video";
export type MediaSource = "local" | "google_drive";
export interface MediaItem { id: string; source: MediaSource; drive_file_id?: string; path: string; type: MediaType; orientation: Orientation; width: number; height: number; duration_sec: number; order_index: number; fit_mode?: FitMode; background_fill?: BackgroundFill; trim_start_sec?: number; trim_end_sec?: number; source_fps?: number; face_count?: number; people_count?: number; importance_score?: number; vision_ai_used?: boolean; scene_type?: string; ai_duration_sec?: number; ai_edit_score?: number; music_sync?: boolean; }
export interface AudioTrack { id?: string; name?: string; path?: string; duration_sec: number; bpm: number; beat_times_sec?: number[]; beat_markers_sec: number[]; energy_curve: number[]; }
export type AudioInfo = AudioTrack;
export interface OutputSpec { resolution: string; fps: number; background_fill: BackgroundFill; vcodec: "h264" | "h265"; }
export interface KenBurnsParams { movement: string; params: Record<string, unknown>; }
export interface EditEntry { media_id: string; duration_sec: number; transition_out: number; start_sec_in_final_video: number; ken_burns?: KenBurnsParams; }
export interface ClipOverride { duration_sec?: number; transition_out?: number; ken_burns_movement?: string; }
export interface JobProgress { fraction: number; label?: string; note?: string; }
export interface Job { id: string; kind: "render" | "drive_import" | "intake"; status: "pending" | "running" | "completed" | "failed"; error?: string; created_at: string; updated_at: string; progress?: JobProgress; }
export interface PipelineLogEntry { stage: string; status: "pending" | "running" | "completed" | "failed"; message?: string; timestamp?: number; }
export interface RenderManifestOutput { path: string; resolution: string; fps: number; vcodec: "libx264" | "libx265"; preset: string; crf: number; duration_sec?: number; size_bytes?: number; rendered_at?: number; }
export interface InputEntry { index: number; path: string; kind: "video" | "photo" | "audio"; audio_track?: number; }
export interface SegmentEntry { media_id: string; input_index: number; kind: "video" | "photo"; fit: "cover" | "contain"; label: string; filter: string; duration_sec: number; }
export interface TransitionEntry { index: number; from_segment: number; to_segment: number; duration_sec: number; offset_sec: number; cut: boolean; }
export interface AudioTrackInfo { path?: string; name?: string; duration_sec: number; }
export interface AudioBlock { tracks: AudioTrackInfo[]; }
export interface ValidationReport { codec: string; width: number; height: number; duration: number; size_bytes: number; }
export interface RenderManifest { version: number; status: "ready" | "running" | "done" | "failed"; inputs: InputEntry[]; segments: SegmentEntry[]; transitions: TransitionEntry[]; filter_complex?: string; filter_complex_script: string; args: string[]; total_sec: number; output: RenderManifestOutput; audio?: AudioBlock; fps: number; resolution: string; vcodec: string; source_video_audio: "muted" | "mixed"; validation?: ValidationReport | null; }
export interface QAReport { status: "approved" | "rejected"; checks?: { name: string; passed: boolean; detail: string }[]; issues?: { check: string; message: string; route_to: string }[]; }
export interface ProjectError { stage: string; message: string; detail?: string; }
export interface StoryChapter { title: string; kind: string; media_ids: string[]; start_index: number; end_index: number; reason?: string; }
export interface MusicStructure { duration_sec?: number; bpm?: number; energy?: string; sections?: { start_sec: number; end_sec: number; label: string; energy: number }[]; climax_sec?: number; peak_energy?: number; }
export interface AIFeedback { rating: "up" | "down"; reasons: string[]; note: string; created_at: number; }
export interface ProjectState { schema_version: number; project_id: string; name: string; user_prompt: string; media: MediaItem[]; audio: AudioTrack; audio_tracks?: AudioTrack[]; style_profile: string; output_spec: OutputSpec; edit_decision_list: EditEntry[]; story_chapters: StoryChapter[]; music_structure: MusicStructure; clip_overrides: Record<string, ClipOverride>; ai_feedback?: AIFeedback | null; ai_feedback_history?: AIFeedback[]; render_manifest?: RenderManifest; qa_report?: QAReport; errors: ProjectError[]; pipeline_log: PipelineLogEntry[]; created_at: number; updated_at: number; }
export interface ProgressSnapshot { jobs: Job[]; pipeline_log: PipelineLogEntry[]; updated_at: number; errors_count: number; media_count: number; has_audio: boolean; has_edit: boolean; has_render: boolean; qa_status?: string; }
export interface SettingsPatch { background_fill?: BackgroundFill; resolution?: string; fps?: number; vcodec?: "h264" | "h265"; }
export interface ProjectPatch { name?: string; user_prompt?: string; style_profile?: string; }
export interface FeedbackRequest { rating: "up" | "down"; reasons?: string[]; note?: string; }

export const API_BASE_VALUE = API_BASE;
const DIRECT_API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> { const c = new AbortController(); const t = setTimeout(() => c.abort(), 120000); try { const r = await fetch(url, { ...options, signal: c.signal, headers: { ...(options?.headers || {}), "Content-Type": "application/json" } }); clearTimeout(t); if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`); return r.json(); } catch (e) { clearTimeout(t); if (e instanceof Error && e.name === "AbortError") throw new Error("Timeout della richiesta: il server non ha risposto entro 2 minuti"); throw e; } }
export async function getHealth(): Promise<HealthResponse> { return fetchJson(`${API_BASE}/health`); }
export async function createProject(): Promise<ProjectState> { return fetchJson(`${API_BASE}/projects`, { method: "POST" }); }
export async function listProjects(): Promise<ProjectSummary[]> { return fetchJson(`${API_BASE}/projects`); }
export async function deleteProject(projectId: string): Promise<void> { const r = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" }); if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`); }
export async function getProject(projectId: string): Promise<ProjectState> { return fetchJson(`${API_BASE}/projects/${projectId}`); }
export async function updateProject(projectId: string, patch: ProjectPatch): Promise<ProjectState> { return fetchJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}`, { method: "PATCH", body: JSON.stringify(patch) }); }
export async function duplicateProject(projectId: string): Promise<ProjectState> { return fetchJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}/duplicate`, { method: "POST" }); }
export async function submitFeedback(projectId: string, feedback: FeedbackRequest): Promise<ProjectState> { return fetchJson(`${API_BASE}/projects/${encodeURIComponent(projectId)}/feedback`, { method: "POST", body: JSON.stringify(feedback) }); }

export async function uploadMedia(projectId: string, files: File[]): Promise<ProjectState> { const formData = new FormData(); files.forEach(f => formData.append("files", f)); const c = new AbortController(); const t = setTimeout(() => c.abort(), 300000); try { const r = await fetch(`${DIRECT_API_BASE}/api/projects/${projectId}/media`, { method: "POST", signal: c.signal, body: formData }); clearTimeout(t); if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`); return r.json(); } catch (e) { clearTimeout(t); if (e instanceof Error && e.name === "AbortError") throw new Error("Upload scaduto: il file è molto grande o la connessione è lenta."); throw e instanceof Error ? e : new Error("Errore sconosciuto durante l'upload"); } }
export async function reorderMedia(projectId: string, mediaIds: string[]): Promise<ProjectState> { return fetchJson(`${API_BASE}/projects/${projectId}/media/order`, { method: "PUT", body: JSON.stringify({ media_ids: mediaIds }) }); }
export async function updateMediaFill(projectId: string, mediaId: string, fill: BackgroundFill): Promise<ProjectState> { return fetchJson(`${API_BASE}/projects/${projectId}/media/${mediaId}`, { method: "PATCH", body: JSON.stringify({ background_fill: fill }) }); }
export async function updateSettings(projectId: string, patch: SettingsPatch): Promise<ProjectState> { return fetchJson(`${API_BASE}/projects/${projectId}/settings`, { method: "PATCH", body: JSON.stringify(patch) }); }
export async function uploadAudio(projectId: string, file: File): Promise<ProjectState> { const formData = new FormData(); formData.append("file", file); const c = new AbortController(); const t = setTimeout(() => c.abort(), 300000); try { const r = await fetch(`${DIRECT_API_BASE}/api/projects/${projectId}/audio`, { method: "POST", signal: c.signal, body: formData }); clearTimeout(t); if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`); return r.json(); } catch (e) { clearTimeout(t); if (e instanceof Error && e.name === "AbortError") throw new Error("Upload audio scaduto: riprova con un file più piccolo"); throw e instanceof Error ? e : new Error("Errore sconosciuto durante l'upload audio"); } }
export async function planEdit(projectId: string): Promise<ProjectState> { return fetchJson(`${API_BASE}/projects/${projectId}/edit`, { method: "POST" }); }
export async function patchClipOverride(projectId: string, mediaId: string, patch: ClipOverride): Promise<ProjectState> { return fetchJson(`${API_BASE}/projects/${projectId}/edit/clips/${mediaId}`, { method: "PATCH", body: JSON.stringify(patch) }); }
export async function resetClipOverride(projectId: string, mediaId: string): Promise<ProjectState> { return fetchJson(`${API_BASE}/projects/${projectId}/edit/clips/${mediaId}`, { method: "DELETE" }); }
export async function submitRenderJob(projectId: string): Promise<ProjectState | { job: Job }> { const r = await fetch(`${API_BASE}/projects/${projectId}/render?background=true`, { method: "POST" }); if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`); return r.json(); }
export async function submitDriveImportJob(projectId: string, fileIds: string[], folderIds: string[], background = true): Promise<ProjectState | { job: Job }> { const r = await fetch(`${API_BASE}/projects/${projectId}/drive/import${background ? "?background=true" : ""}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_ids: fileIds, folder_ids: folderIds }) }); if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`); return r.json(); }
export async function clearErrors(projectId: string): Promise<ProjectState> { return fetchJson(`${API_BASE}/projects/${projectId}/errors/clear`, { method: "POST" }); }
export function getEventSourceUrl(projectId: string): string { return `${API_BASE}/projects/${projectId}/events`; }
export interface DriveEntry { id: string; name: string; mimeType: string; is_folder: boolean; }
export interface DriveStatus { configured: boolean; connected: boolean; email?: string; }
export async function driveAuthUrl(): Promise<string> { return (await fetchJson<{ url: string }>(`${API_BASE}/drive/auth-url`)).url; }
export async function saveDriveCredentials(clientId: string, clientSecret: string): Promise<void> { const r = await fetch(`${API_BASE}/drive/credentials`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }) }); if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`); }
export async function driveStatus(): Promise<DriveStatus> { return fetchJson(`${API_BASE}/drive/status`); }
export async function driveDisconnect(): Promise<void> { const r = await fetch(`${API_BASE}/drive/disconnect`, { method: "POST" }); if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`); }
export async function driveListFiles(projectId: string, folderId?: string, pageToken?: string, shared = false): Promise<{ current: { id: string; name: string }; entries: DriveEntry[]; nextPageToken?: string }> { const p = new URLSearchParams(); if (folderId) p.set("folder_id", folderId); if (pageToken) p.set("page_token", pageToken); if (shared) p.set("shared", "true"); const q = p.toString(); return fetchJson(`${API_BASE}/projects/${projectId}/drive/files${q ? `?${q}` : ""}`); }
export function isJobActive(job?: Job | null): boolean { return !!job && (job.status === "pending" || job.status === "running"); }
export function mediaThumbUrl(projectId: string, mediaId: string): string { return `${API_BASE}/projects/${projectId}/media/${mediaId}/thumb`; }
export const CLIP_MOVEMENTS = [{ value: "static", label: "Fisso" }, { value: "pan_left", label: "Pan sinistra" }, { value: "pan_right", label: "Pan destra" }, { value: "zoom_in_slow", label: "Zoom in" }, { value: "zoom_out_slow", label: "Zoom out" }, { value: "pan_and_zoom_diag", label: "Diagonale" }] as const;
export function downloadUrl(projectId: string): string { return `${API_BASE}/projects/${projectId}/download`; }
