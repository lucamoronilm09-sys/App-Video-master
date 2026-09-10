import { API_BASE, type ProjectState } from "@/lib/api";

export async function deleteMedia(projectId: string, mediaId: string): Promise<ProjectState> {
  const res = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/media/${encodeURIComponent(mediaId)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  const data = await res.json();
  if (!data?.state || typeof data.state !== "object" || !Array.isArray(data.state.media)) {
    throw new Error("Risposta del server non valida durante l'eliminazione");
  }
  return data.state as ProjectState;
}
