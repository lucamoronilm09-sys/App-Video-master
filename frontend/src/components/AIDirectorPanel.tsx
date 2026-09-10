"use client";

import { useEffect, useState } from "react";
import type { MusicStructure, ProjectState, StoryChapter } from "@/lib/api";

interface Props {
  project: ProjectState;
  onSave: (patch: { user_prompt?: string; style_profile?: string }) => Promise<void>;
  busy?: boolean;
}

const STYLES = [
  ["album_memory", "Ricordi cinematografici"], ["cinematic", "Cinematico"], ["dynamic", "Dinamico"],
  ["emotional", "Emozionante"], ["travel", "Viaggio"], ["family", "Famiglia"], ["sport", "Sport/azione"],
];

function StoryCard({ chapters }: { chapters: StoryChapter[] }) {
  if (!chapters.length) return <p className="text-xs text-slate-500">Genera il montaggio per far analizzare la storia delle immagini.</p>;
  return <div className="grid gap-2 sm:grid-cols-2">{chapters.map((c, i) => <div key={`${c.start_index}-${c.end_index}-${i}`} className="rounded-xl border border-white/5 bg-black/20 p-3"><div className="flex items-center justify-between"><span className="text-sm font-semibold text-white">{c.title}</span><span className="text-[10px] text-slate-500">{c.media_ids.length} media</span></div><p className="mt-1 text-[11px] text-slate-500">{c.reason}</p></div>)}</div>;
}

function MusicCard({ music }: { music: MusicStructure }) {
  if (!music.sections?.length) return <p className="text-xs text-slate-500">Carica una traccia audio per analizzarne struttura e climax.</p>;
  return <div><div className="mb-3 flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-white/5 px-2 py-1 text-slate-300">BPM {music.bpm?.toFixed(0) ?? "—"}</span><span className="rounded-full bg-white/5 px-2 py-1 text-slate-300">Energia {music.energy ?? "—"}</span><span className="rounded-full bg-violet-500/10 px-2 py-1 text-violet-200">Climax {music.climax_sec?.toFixed(1) ?? "—"}s</span></div><div className="grid grid-cols-2 gap-2 lg:grid-cols-4">{music.sections.map(s => <div key={`${s.start_sec}-${s.label}`} className="rounded-xl border border-white/5 bg-black/20 p-3"><p className="text-xs font-semibold text-white">{s.label}</p><p className="mt-1 text-[11px] text-slate-500">{s.start_sec.toFixed(1)}–{s.end_sec.toFixed(1)}s</p><div className="mt-2 h-1 rounded-full bg-white/10"><div className="h-1 rounded-full bg-violet-400" style={{ width: `${Math.round(s.energy * 100)}%` }} /></div></div>)}</div></div>;
}

export function AIDirectorPanel({ project, onSave, busy }: Props) {
  const [prompt, setPrompt] = useState(project.user_prompt ?? "");
  const [style, setStyle] = useState(project.style_profile || "album_memory");
  const [saved, setSaved] = useState(true);
  useEffect(() => { setPrompt(project.user_prompt ?? ""); setStyle(project.style_profile || "album_memory"); }, [project.user_prompt, project.style_profile]);

  const save = async () => { setSaved(false); try { await onSave({ user_prompt: prompt, style_profile: style }); setSaved(true); } catch { setSaved(false); } };

  return <section aria-label="AI Director" className="rounded-xl border border-violet-400/15 bg-slate-900/50 p-4">
    <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"><div><h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300">AI Director</h3><p className="mt-1 text-xs text-slate-500">Descrivi il risultato che vuoi: il regista usa il testo per modulare scelta, ritmo e durata.</p></div>{!saved && <span className="text-[11px] text-amber-300">Salvataggio…</span>}</div>
    <div className="grid gap-3 lg:grid-cols-[1fr_240px_auto] lg:items-end">
      <label className="text-xs text-slate-400"><span className="mb-1 block">Cosa vuoi raccontare?</span><textarea value={prompt} disabled={busy} onChange={e => setPrompt(e.target.value)} onBlur={() => void save()} rows={3} maxLength={2000} placeholder="Es. viaggio emozionante tra amici, più persone nei momenti chiave e finale lento…" className="w-full resize-y rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 outline-none ring-violet-400/30 placeholder:text-slate-600 focus:ring-2 disabled:opacity-50" /></label>
      <label className="text-xs text-slate-400"><span className="mb-1 block">Stile</span><select value={style} disabled={busy} onChange={e => { setStyle(e.target.value); void onSave({ style_profile: e.target.value, user_prompt: prompt }); }} className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 disabled:opacity-50">{STYLES.map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      <button type="button" disabled={busy} onClick={() => void save()} className="rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-500 disabled:opacity-50">Salva istruzioni</button>
    </div>
    <div className="mt-5 grid gap-4 xl:grid-cols-2"><div><div className="mb-2 flex items-center justify-between"><h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Storia rilevata</h4><span className="text-[10px] text-slate-600">AI</span></div><StoryCard chapters={project.story_chapters ?? []} /></div><div><div className="mb-2 flex items-center justify-between"><h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Struttura musicale</h4><span className="text-[10px] text-slate-600">AI</span></div><MusicCard music={project.music_structure ?? {}} /></div></div>
  </section>;
}
