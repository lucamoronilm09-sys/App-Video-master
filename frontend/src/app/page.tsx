"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getHealth, createProject, listProjects, deleteProject, type HealthResponse, type ProjectSummary } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    const poll = async () => {
      try {
        const [h, ps] = await Promise.all([getHealth(), listProjects()]);
        setHealth(h);
        setProjects(ps);
        setError(null);
      } catch {
        setError("Backend non raggiungibile (uvicorn attivo su :8000?)");
      }
    };
    poll();
    timer = setInterval(poll, 5000);
    return () => { if (timer) clearInterval(timer); };
  }, []);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const { project_id } = await createProject();
      router.push(`/projects/${project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore creazione progetto");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (projectId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`Sei sicuro di voler eliminare il progetto ${projectId}?`)) {
      return;
    }
    setDeleting(projectId);
    try {
      await deleteProject(projectId);
      setProjects(projects.filter(p => p.project_id !== projectId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore eliminazione progetto");
    } finally {
      setDeleting(null);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center gap-8 px-6 py-12">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight">AI Video Maker</h1>
        <p className="mt-3 text-slate-400 max-w-md">
          Slideshow automatico in stile album/ricordo, montato e sincronizzato
          con la tua musica.
        </p>
      </div>

      <div className="w-full rounded-xl border border-slate-800 bg-slate-900/60 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            Stato backend
          </h2>
          <span className={`h-3 w-3 rounded-full ${health ? "bg-emerald-400" : "bg-rose-500"}`} />
        </div>
        <div className="text-sm text-slate-200">
          {health ? (
            <>
              {health.service} &mdash; progetti: {health.projects_count}
            </>
          ) : (
            <span className="text-rose-300">{error ?? "Connessione in corso&hellip;"}</span>
          )}
        </div>
      </div>

      <div className="w-full">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            I tuoi progetti
          </h2>
          <button
            onClick={handleCreate}
            disabled={creating || !health}
            className="px-4 py-2 text-sm font-medium text-slate-900 bg-emerald-400 rounded-lg hover:bg-emerald-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {creating ? "Creazione&hellip;" : "Nuovo progetto"}
          </button>
        </div>

        {projects.length === 0 ? (
          <div className="text-center py-12 border-2 border-dashed border-slate-700 rounded-xl">
            <p className="text-slate-500">Nessun progetto. Clicca &ldquo;Nuovo progetto&rdquo; per iniziare.</p>
          </div>
        ) : (
          <ul className="space-y-3">
            {projects.map(p => (
              <li key={p.project_id} className="flex items-center justify-between p-4 rounded-lg bg-slate-900/60 border border-slate-800 hover:border-slate-700 transition-colors">
                <div className="flex items-center gap-3">
                  <span className="h-2 w-2 rounded-full bg-emerald-400" />
                  <div>
                    <p className="font-mono text-sm">{p.project_id}</p>
                    <p className="text-xs text-slate-400">
                      {p.media_count} media &middot; {p.has_audio ? "con audio" : "senza audio"} &middot; {p.has_render ? "render pronto" : "da montare"}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => router.push(`/projects/${p.project_id}`)}
                    className="px-3 py-1 text-xs text-slate-300 hover:text-slate-100 underline"
                  >
                    Apri
                  </button>
                  <button
                    onClick={(e) => handleDelete(p.project_id, e)}
                    disabled={deleting === p.project_id}
                    className="px-3 py-1 text-xs text-rose-400 hover:text-rose-300 underline disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {deleting === p.project_id ? "Elimino&hellip;" : "Elimina"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="text-center text-xs text-slate-500">
        Milestone M1 &mdash; upload multiplo locale + Intake Agent (metadati reali)
      </p>
    </main>
  );
}