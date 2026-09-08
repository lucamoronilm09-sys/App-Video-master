"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  getHealth,
  createProject,
  listProjects,
  deleteProject,
  type HealthResponse,
  type ProjectSummary,
} from "@/lib/api";

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
        const [h, ps] = await Promise.all([
          getHealth(),
          listProjects(),
        ]);

        setHealth(h);
        setProjects(ps);
        setError(null);
      } catch {
        setError(
          "Backend non raggiungibile (uvicorn attivo su :8000?)"
        );
      }
    };

    poll();

    timer = setInterval(poll, 5000);

    return () => {
      if (timer) clearInterval(timer);
    };
  }, []);

  const handleCreate = async () => {
    setCreating(true);

    try {
      const { project_id } = await createProject();

      router.push(`/projects/${project_id}`);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Errore creazione progetto"
      );
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (
    projectId: string,
    e: React.MouseEvent
  ) => {
    e.stopPropagation();

    if (
      !confirm(
        `Sei sicuro di voler eliminare il progetto ${projectId}?`
      )
    ) {
      return;
    }

    setDeleting(projectId);

    try {
      await deleteProject(projectId);

      setProjects(
        projects.filter(
          (p) => p.project_id !== projectId
        )
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Errore eliminazione progetto"
      );
    } finally {
      setDeleting(null);
    }
  };

  return (
    <main className="app-shell min-h-screen px-5 py-8 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-6xl">

        {/* HEADER */}

        <header className="float-in flex items-center justify-between rounded-2xl px-1 py-2">
          <div className="flex items-center gap-3">

            <div className="glow flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 text-sm font-black">
              AI
            </div>

            <div>
              <p className="text-sm font-semibold text-white">
                AI Video Maker
              </p>

              <p className="text-xs text-slate-500">
                Creative workspace
              </p>
            </div>

          </div>

          <div className="surface-soft flex items-center gap-2 rounded-full px-3 py-2 text-xs text-slate-300">

            <span
              className={`pulse-dot h-2 w-2 rounded-full ${
                health
                  ? "bg-emerald-400"
                  : "bg-rose-400"
              }`}
            />

            {health
              ? "Backend online"
              : "Offline"}

          </div>
        </header>

        {/* HERO */}

        <section className="float-in mt-14 grid items-end gap-10 lg:grid-cols-[1.25fr_.75fr]">

          <div>

            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-violet-400/20 bg-violet-400/10 px-3 py-1 text-xs font-medium text-violet-200">
              <span>●</span>
              AI-powered video creation
            </div>

            <h1 className="max-w-3xl text-5xl font-black tracking-tight sm:text-6xl">
              Trasforma i tuoi ricordi in un video{" "}
              <span className="gradient-text">
                cinematografico.
              </span>
            </h1>

            <p className="mt-5 max-w-2xl text-base leading-7 text-slate-400 sm:text-lg">
              Carica foto, video e musica. Organizza la
              timeline, imposta il formato e lascia al
              workspace il compito di assemblare il
              montaggio.
            </p>

            <div className="mt-8 flex flex-wrap gap-3">

              <button
                onClick={handleCreate}
                disabled={creating || !health}
                className="group inline-flex items-center gap-2 rounded-xl bg-white px-5 py-3 text-sm font-bold text-slate-950 shadow-xl shadow-violet-950/20 transition hover:-translate-y-0.5 hover:bg-violet-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creating
                  ? "Creazione…"
                  : "Crea nuovo progetto"}

                <span className="transition-transform group-hover:translate-x-0.5">
                  →
                </span>
              </button>

              <div className="surface-soft rounded-xl px-4 py-3 text-sm text-slate-400">
                <span className="font-semibold text-white">
                  {projects.length}
                </span>{" "}
                progetti salvati
              </div>

            </div>
          </div>

          {/* STATUS CARD */}

          <div className="surface glow rounded-3xl p-5">

            <div className="rounded-2xl border border-white/10 bg-black/20 p-5">

              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>
                  WORKSPACE STATUS
                </span>

                <span>
                  {health
                    ? "READY"
                    : "CHECK CONNECTION"}
                </span>
              </div>

              <div className="mt-6 grid grid-cols-3 gap-3">

                {[
                  ["01", "Import"],
                  ["02", "Montage"],
                  ["03", "Export"],
                ].map(([n, label]) => (
                  <div
                    key={n}
                    className="surface-soft rounded-2xl p-4"
                  >
                    <p className="text-[11px] font-bold text-violet-300">
                      {n}
                    </p>

                    <p className="mt-2 text-sm font-semibold text-white">
                      {label}
                    </p>
                  </div>
                ))}

              </div>

              <div className="mt-5 rounded-2xl bg-gradient-to-br from-violet-500/15 to-fuchsia-500/10 p-4">

                <p className="text-xs uppercase tracking-[0.2em] text-slate-500">
                  Backend
                </p>

                <p className="mt-2 text-lg font-semibold text-white">
                  {health?.service ??
                    "Connessione in corso…"}
                </p>

                <p className="mt-1 text-xs text-slate-500">
                  {health
                    ? `${health.projects_count} progetti sincronizzati`
                    : error}
                </p>

              </div>

            </div>
          </div>
        </section>

        {/* PROJECT LIBRARY */}

        <section className="float-in mt-12">

          <div className="mb-5 flex items-end justify-between">

            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
                Library
              </p>

              <h2 className="mt-1 text-2xl font-bold text-white">
                I tuoi progetti
              </h2>
            </div>

            {error && (
              <p className="max-w-sm text-right text-xs text-rose-300">
                {error}
              </p>
            )}

          </div>

          {projects.length === 0 ? (

            <div className="surface rounded-3xl border-dashed px-6 py-20 text-center">

              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-white/5 text-2xl">
                ＋
              </div>

              <h3 className="mt-5 text-lg font-semibold text-white">
                Nessun progetto ancora
              </h3>

              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
                Inizia creando il tuo primo progetto e
                porta dentro foto, video e musica.
              </p>

            </div>

          ) : (

            <div className="grid gap-4 md:grid-cols-2">

              {projects.map((p) => (

                <article
                  key={p.project_id}
                  onClick={() =>
                    router.push(
                      `/projects/${p.project_id}`
                    )
                  }
                  className="surface group cursor-pointer rounded-3xl p-5 transition duration-200 hover:-translate-y-1 hover:border-violet-400/20"
                >

                  <div className="flex items-start justify-between gap-4">

                    <div className="flex items-center gap-3">

                      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500/20 to-fuchsia-500/20 text-sm font-bold text-violet-200">
                        ▶
                      </div>

                      <div>

                        <p className="font-mono text-sm font-semibold text-white">
                          {p.project_id.slice(
                            0,
                            12
                          )}
                        </p>

                        <p className="mt-1 text-xs text-slate-500">
                          Apri workspace →
                        </p>

                      </div>

                    </div>

                    <button
                      onClick={(e) =>
                        handleDelete(
                          p.project_id,
                          e
                        )
                      }
                      disabled={
                        deleting ===
                        p.project_id
                      }
                      className="rounded-lg px-2 py-1 text-xs text-slate-500 transition hover:bg-rose-400/10 hover:text-rose-300 disabled:opacity-40"
                    >
                      {deleting ===
                      p.project_id
                        ? "…"
                        : "Elimina"}
                    </button>

                  </div>

                  <div className="mt-6 grid grid-cols-3 gap-2">

                    <div className="surface-soft rounded-xl p-3">
                      <p className="text-[11px] text-slate-500">
                        Media
                      </p>

                      <p className="mt-1 text-sm font-semibold text-white">
                        {p.media_count}
                      </p>
                    </div>

                    <div className="surface-soft rounded-xl p-3">
                      <p className="text-[11px] text-slate-500">
                        Audio
                      </p>

                      <p className="mt-1 text-sm font-semibold text-white">
                        {p.has_audio
                          ? "Sì"
                          : "No"}
                      </p>
                    </div>

                    <div className="surface-soft rounded-xl p-3">
                      <p className="text-[11px] text-slate-500">
                        Render
                      </p>

                      <p className="mt-1 text-sm font-semibold text-white">
                        {p.has_render
                          ? "Pronto"
                          : "Da fare"}
                      </p>
                    </div>

                  </div>

                </article>

              ))}

            </div>
          )}

        </section>

        <footer className="py-10 text-center text-xs text-slate-600">
          AI Video Maker · Milestone M1–M8
        </footer>

      </div>
    </main>
  );
}
