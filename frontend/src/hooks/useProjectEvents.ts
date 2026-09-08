"use client";

import { useEffect, useState } from "react";
import { API_BASE, type ProgressSnapshot } from "@/lib/api";

/** M8: sottoscrizione SSE agli avanzamenti del progetto (riconnessione automatica). */
export function useProjectEvents(projectId: string): ProgressSnapshot | null {
  const [snapshot, setSnapshot] = useState<ProgressSnapshot | null>(null);

  useEffect(() => {
    const src = new EventSource(`${API_BASE}/api/projects/${projectId}/events`);
    src.onmessage = e => {
      try {
        setSnapshot(JSON.parse(e.data) as ProgressSnapshot);
      } catch {
        // payload malformato: ignora, il prossimo snapshot rimedia
      }
    };
    src.onerror = () => {
      // EventSource ritenta da solo; se il progetto sparisce, il server chiude
      if (src.readyState === EventSource.CLOSED) src.close();
    };
    return () => src.close();
  }, [projectId]);

  return snapshot;
}
