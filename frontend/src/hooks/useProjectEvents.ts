"use client";

import { useEffect, useState } from "react";
import { API_BASE, type ProgressSnapshot } from "@/lib/api";

/**
 * M8: SSE con fallback HTTP.
 *
 * SSE resta il canale principale, ma la UI non deve dipendere da una singola
 * connessione EventSource: su localhost, proxy/reload e reti instabili possono
 * interromperla mentre il worker continua tranquillamente. In parallelo
 * interroghiamo uno snapshot leggero ogni 3 secondi.
 */
export function useProjectEvents(projectId: string): ProgressSnapshot | null {
  const [snapshot, setSnapshot] = useState<ProgressSnapshot | null>(null);

  useEffect(() => {
    let disposed = false;

    const apply = (next: ProgressSnapshot) => {
      if (!disposed) setSnapshot(next);
    };

    const src = new EventSource(`${API_BASE}/projects/${projectId}/events`);
    src.onmessage = e => {
      try {
        apply(JSON.parse(e.data) as ProgressSnapshot);
      } catch {
        // Payload malformato: il polling HTTP può comunque recuperare lo stato.
      }
    };
    src.onerror = () => {
      // EventSource ritenta da solo. Il polling continua indipendentemente.
    };

    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/projects/${projectId}/progress`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (!res.ok) return;
        apply((await res.json()) as ProgressSnapshot);
      } catch {
        // SSE o il prossimo ciclo di polling possono recuperare lo stato.
      }
    };

    void poll();
    const timer = setInterval(() => void poll(), 3000);

    return () => {
      disposed = true;
      clearInterval(timer);
      src.close();
    };
  }, [projectId]);

  return snapshot;
}
