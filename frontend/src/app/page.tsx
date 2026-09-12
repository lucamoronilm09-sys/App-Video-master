"use client";

import { useEffect, useState, type MouseEvent } from "react";
import Link from "next/link";
import {
  createProject,
  deleteProject,
  duplicateProject,
  getHealth,
  listProjects,
  type HealthResponse,
  type ProjectSummary,
} from "@/lib/api";

function ProjectCard({
  project,
  deleting,
  duplicating,
  onDelete,
  onDuplicate,
}: {
  project: ProjectSummary;
  deleting: boolean;
  duplicating: boolean;
  onDelete: (projectId: string, event: MouseEvent<HTMLButtonElement>) => void;
  onDuplicate: (projectId: string, event: MouseEvent<HTMLButtonElement>) => void;
}) {
  return (
    <article className="surface rounded-3xl p-5 transition duration-200 hover:-translate-y-1 hover:border-violet-400/20">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <div
            aria-hidden="true"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500/20 to-fuchsia-500/20 text-sm font-bold text-violet-200"
          >
            ▶
          </div>
          <div className="min-w-0">
            <Link
              href={`/projects/${project.project_id}`}
              className="block truncate font-semibold text-white underline-offset-4 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
            >
              {project.name || "Nuovo progetto"}
            </Link>
            <p className="mt-1 font-mono text-[10px] text-slate-600">
              {project.project_id}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 gap-1">
          <button
            type="button"
            onClick={(event) => onDuplicate(project.project_id, event)}
            disabled={duplicating || deleting}
            aria-label={`Duplica ${project.name || "progetto"}`}
            className="rounded-lg px-2 py-1 text-xs text-slate-500 transition hover:bg-white/5 hover:text-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {duplicating ? "…" : "Copia"}
          </button>
          <button
            type="button"
            onClick={(event) => onDelete(project.project_id, event)}
            disabled={deleting || duplicating}
            aria-label={`Elimina ${project.name || "progetto"}`}
            className="rounded-lg px-2 py-1 text-xs text-slate-500 transition hover:bg-rose-400/10 hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {deleting ? "…" : "Elimina"}
          </button>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-3 gap-2">
        <div className="surface-soft rounded-xl p-3">
          <p className="text-[11px] text-slate-500">Media</p>
          <p className="mt-1 text-sm font-semibold text-white">
            {project.media_count}
          </p>
        </div>
        <div className="surface-soft rounded-xl p-3">
          <p className="text-[11px] text-slate-500">Audio</p>
          <p className="mt-1 text-sm font-semibold text-white">
            {project.has_audio ? "Sì" : "No"}
          </p>
        </div>
        <div className="surface-soft rounded-xl p-3">
          <p className="text-[11px] text-slate-500">Render</p>
          <p className="mt-1 text-sm font-semibold text-white">
            {project.has_render ? "Pronto" : "Da fare"}
          </p>
        </div>
      </div>
    </article>
  );
}

export default function Home() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [duplicating, setDuplicating] = useState<string | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    let disposed = false;

    const poll = async () => {
      try {
        const [nextHealth, nextProjects] = await Promise.all([
          getHealth(),
          listProjects(),
        ]);
        if (disposed) return;
        setHealth(nextHealth);
        setProjects(nextProjects);
        setError(null);
      } catch {
        if (disposed) return;
        setHealth(null);
        setError("Backend non raggiungibile (uvicorn attivo su :8000?)");
      }
    };

    void poll();
    timer = setInterval(() => void poll(), 5000);

    return () => {
      disposed = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      const { project_id } = await createProject();
      window.location.assign(`/projects/${project_id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Errore creazione progetto");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (
    projectId: string,
    event: MouseEvent<HTMLButtonElement>,
  ) => {
    event.preventDefault();
    setDeleting(projectId);
    setError(null);

    try {
      if (!window.confirm("Sei sicuro di voler eliminare questo progetto?")) {
        return;
      }
      await deleteProject(projectId);
      setProjects((current) =>
        current.filter((project) => project.project_id !== projectId),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Errore eliminazione progetto");
    } finally {
      setDeleting(null);
    }
  };

  const handleDuplicate = async (
    projectId: string,
    event: MouseEvent<HTMLButtonElement>,
  ) => {
    event.preventDefault();
    setDuplicating(projectId);
    setError(null);

    try {
      const project = await duplicateProject(projectId);
      setProjects((current) => [
        {
          project_id: project.project_id,
          name: project.name,
          media_count: project.media.length,
          has_audio: Boolean(project.audio?.path),
          has_render: project.render_manifest?.status === "done",
          updated_at: project.updated_at,
        },
        ...current,
      ]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Errore duplicazione progetto");
    } finally {
      setDuplicating(null);
    }
  };

  return (
    <main className="app-shell min-h-screen px-5 py-8 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-6xl">
        <header className="float-in flex items-center justify-between rounded-2xl px-1 py-2">
          <div className="flex items-center gap-3">
            <div
              aria-hidden="true"
              className="glow flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 text-sm font-black"
            >
              AI
            </div>
            <div>
              <p className="text-sm font-semibold text-white">AI Video Maker</p>
              <p className="text-xs text-slate-500">Creative workspace</p>
            </div>
          </div>
          <div className="surface-soft flex items-center gap-2 rounded-full px-3 py-2 text-xs text-slate-300" role="status" aria-live="polite">
            <span
              aria-hidden="true"
              className={`pulse-dot h-2 w-2 rounded-full ${health ? "bg-emerald-400" : "bg-rose-400"}`}
            />
            {health ? "Backend online" : "Offline"}
          </div>
        </header>

        <section className="float-in mt-14 grid items-end gap-10 lg:grid-cols-[1.25fr_.75fr]">
          <div>
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-violet-400/20 bg-violet-400/10 px-3 py-1 text-xs font-medium text-violet-200">
              <span aria-hidden="true">●</span>
              AI-powered video creation
            </div>
            <h1 className="max-w-3xl text-5xl font-black tracking-tight sm:text-6xl">
              Trasforma i tuoi ricordi in un video{" "}
              <span className="gradient-text">cinematografico.</span>
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-slate-400 sm:text-lg">
              Carica foto, video e musica. L&apos;AI comprende contenuti, storia e
              musica, costruisce il montaggio e ti lascia il controllo finale.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void handleCreate()}
                disabled={creating || !health}
                className="group inline-flex items-center gap-2 rounded-xl bg-white px-5 py-3 text-sm font-bold text-slate-950 shadow-xl shadow-violet-950/20 transition hover:-translate-y-0.5 hover:bg-violet-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creating ? "Creazione…" : "Crea nuovo progetto"}
                <span aria-hidden="true">→</span>
              </button>
              <div className="surface-soft rounded-xl px-4 py-3 text-sm text-slate-400">
                <span className="font-semibold text-white">{projects.length}</span>{" "}
                progetti salvati
              </div>
            </div>
          </div>

          <div className="surface glow rounded-3xl p-5">
            <div className="rounded-2xl border border-white/10 bg-black/20 p-5">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>WORKSPACE STATUS</span>
                <span>{health ? "READY" : "CHECK CONNECTION"}</span>
              </div>
              <div className="mt-6 grid grid-cols-3 gap-3">
                {[
                  ["01", "Import"],
                  ["02", "Montage"],
                  ["03", "Export"],
                ].map(([number, label]) => (
                  <div key={number} className="surface-soft rounded-2xl p-4">
                    <p className="text-[11px] font-bold text-violet-300">{number}</p>
                    <p className="mt-2 text-sm font-semibold text-white">{label}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="float-in mt-12" aria-labelledby="projects-title">
          <div className="mb-5 flex items-end justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
                Library
              </p>
              <h2 id="projects-title" className="mt-1 text-2xl font-bold text-white">
                I tuoi progetti
              </h2>
            </div>
            {error && (
              <p className="max-w-sm text-right text-xs text-rose-300" role="alert">
                {error}
              </p>
            )}
          </div>

          {projects.length === 0 ? (
            <div className="surface rounded-3xl border-dashed px-6 py-20 text-center">
              <div
                aria-hidden="true"
                className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-white/5 text-2xl"
              >
                ＋
              </div>
              <h3 className="mt-5 text-lg font-semibold text-white">
                Nessun progetto ancora
              </h3>
              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
                Inizia creando il tuo primo progetto.
              </p>
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {projects.map((project) => (
                <ProjectCard
                  key={project.project_id}
                  project={project}
                  deleting={deleting === project.project_id}
                  duplicating={duplicating === project.project_id}
                  onDelete={handleDelete}
                  onDuplicate={handleDuplicate}
                />
              ))}
            </div>
          )}
        </section>

        <footer className="py-10 text-center text-xs text-slate-600">
          AI Video Maker · AI Director
        </footer>
      </div>
    </main>
  );
}
