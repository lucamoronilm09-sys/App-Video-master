"use client";

import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";

interface ErrorPanelProps {
  errors: { stage: string; message: string }[];
  onClear: () => Promise<void>;
  busy?: boolean;
}

/** M8: errori non bloccanti con pulizia esplicita dopo visione.
 * Mostra messaggio leggibile + dettagli tecnici espandibili. */
export function ErrorPanel({ errors, onClear, busy }: ErrorPanelProps) {
  const [expandedIndices, setExpandedIndices] = useState<Set<number>>(new Set());

  if (errors.length === 0) return null;

  const toggleExpand = (index: number) => {
    const newSet = new Set(expandedIndices);
    if (newSet.has(index)) {
      newSet.delete(index);
    } else {
      newSet.add(index);
    }
    setExpandedIndices(newSet);
  };

  return (
    <div className="rounded-lg border border-rose-800 bg-rose-900/30 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-rose-400" />
          <h4 className="font-medium text-rose-300">
            Errori ({errors.length})
          </h4>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onClear()}
          className="text-xs text-rose-300/80 hover:text-rose-200 hover:underline disabled:opacity-50"
        >
          Pulisci
        </button>
      </div>
      <ul className="space-y-3">
        {errors.map((e, i) => {
          const isExpanded = expandedIndices.has(i);
          // Cerca di estrarre un messaggio più leggibile
          const summary = extractReadableMessage(e.message);
          const hasDetails = summary !== e.message;

          return (
            <li key={i} className="rounded border border-rose-800/50 bg-rose-950/30 p-3">
              <div className="flex items-start gap-2">
                <span className="mt-0.5 text-xs font-mono text-rose-400">[{e.stage}]</span>
                <div className="flex-1">
                  <p className="text-sm text-rose-200">{summary}</p>
                  
                  {hasDetails && (
                    <div className="mt-2">
                      <button
                        onClick={() => toggleExpand(i)}
                        className="flex items-center gap-1 text-xs text-rose-400/80 hover:text-rose-300 underline"
                      >
                        {isExpanded ? (
                          <>
                            <ChevronUp className="h-3 w-3" /> Nascondi dettagli
                          </>
                        ) : (
                          <>
                            <ChevronDown className="h-3 w-3" /> Mostra dettagli tecnici
                          </>
                        )}
                      </button>
                      
                      {isExpanded && (
                        <pre className="mt-2 max-h-48 overflow-x-auto overflow-y-scroll rounded bg-rose-950/50 p-2 text-xs font-mono text-rose-300/80">
                          {e.message}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Estrae un messaggio leggibile da stderr grezzo di ffmpeg/python. */
function extractReadableMessage(rawMessage: string): string {
  const patterns: Array<{ regex: RegExp; replacement: string }> = [
    { regex: /No such file or directory[:\s]+(.+)/i, replacement: "File non trovato: $1" },
    { regex: /Permission denied[:\s]+(.+)/i, replacement: "Permesso negato: $1" },
    { regex: /No space left on device/i, replacement: "Disco pieno" },
    { regex: /ffmpeg.*not found/i, replacement: "FFmpeg non trovato" },
    { regex: /Invalid data found when processing input/i, replacement: "Dati invalidi nel file" },
    { regex: /Corrupt input packet/i, replacement: "Pacchetto corrotto" },
    { regex: /Encoder .* not found/i, replacement: "Codec non supportato" },
    { regex: /Broken pipe/i, replacement: "Connessione interrotta" },
  ];

  for (const { regex, replacement } of patterns) {
    if (regex.test(rawMessage)) {
      const match = rawMessage.match(regex);
      if (match && match[1]) {
        return replacement.replace("$1", match[1].substring(0, 50));
      }
      return replacement;
    }
  }

  // Se è un errore generico, ritorna il primo rigo significativo
  const lines = rawMessage.split("\n").filter(l => l.trim().length > 0);
  if (lines.length > 1) {
    return lines[0].substring(0, 100) + (lines[0].length > 100 ? "..." : "");
  }

  return rawMessage;
}
