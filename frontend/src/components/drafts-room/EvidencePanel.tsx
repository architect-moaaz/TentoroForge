"use client";

/**
 * A study's evidence: every fact with its standing and its source, filtered
 * by standing and kind. Read from the evidence route when a study is chosen.
 */
import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";
import { StandingDot, STANDING_LABEL } from "./StandingDot";
import type { EvidenceItem, EvidenceKind, Reference, Standing, Study } from "./types";

const STANDINGS: Standing[] = ["observed", "derived", "inferred", "unknown"];
const KINDS: EvidenceKind[] = ["record", "field", "enum", "action", "screen", "flow", "rule", "role", "voice", "gap"];

export function EvidencePanel({ studies, references, fetchEvidence }:
  { studies: Study[]; references: Reference[]; fetchEvidence: (jid: string) => Promise<EvidenceItem[]> }) {
  const withEvidence = studies.filter((s) => (s.evidence_total ?? 0) > 0);
  const [chosen, setChosen] = useState<string | null>(null);
  const [standing, setStanding] = useState<Standing | "">("");
  const [kind, setKind] = useState<EvidenceKind | "">("");
  const [items, setItems] = useState<EvidenceItem[]>([]);
  const study = withEvidence.find((s) => s.id === chosen) ?? withEvidence[withEvidence.length - 1];
  const refName = (id?: string) => references.find((r) => r.id === id)?.name ?? "";

  useEffect(() => {
    if (!study) { setItems([]); return; }
    let gone = false;
    fetchEvidence(study.id).then((rows) => { if (!gone) setItems(rows); }).catch(() => undefined);
    return () => { gone = true; };
  }, [study?.id, study?.evidence_total, fetchEvidence]);

  if (!study) {
    return <p className="text-sm text-muted-foreground py-6 text-center">No evidence yet. It appears as the studies read the reference.</p>;
  }
  const shown = items.filter((i) => (!standing || i.standing === standing) && (!kind || i.kind === kind));
  const counts = study.evidence ?? { observed: 0, derived: 0, inferred: 0, unknown: 0 };
  return (
    <div className="space-y-3 text-sm">
      {withEvidence.length > 1 && (
        <div className="flex flex-wrap gap-1">
          {withEvidence.map((s) => (
            <button key={s.id} onClick={() => setChosen(s.id)}
              className={`text-xs rounded-full border px-2 py-0.5 ${s.id === study.id ? "bg-primary text-primary-foreground" : ""}`}>
              {refName(s.reference_id) || s.reference} · {s.kind === "deep" ? (s.source === "har" ? "your recording" : "deep") : "surface"}
            </button>
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-1">
        <button onClick={() => setStanding("")} className={`text-xs rounded-full border px-2 py-0.5 ${standing === "" ? "bg-primary text-primary-foreground" : ""}`}>
          all {study.evidence_total}
        </button>
        {STANDINGS.map((s) => (
          <button key={s} onClick={() => setStanding(s)} data-testid={`standing-${s}`}
            className={`text-xs rounded-full border px-2 py-0.5 inline-flex items-center gap-1 ${standing === s ? "bg-primary text-primary-foreground" : ""}`}>
            <StandingDot standing={s} /> {STANDING_LABEL[s]} {counts[s] ?? 0}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap gap-1">
        <button onClick={() => setKind("")} className={`text-xs rounded border px-1.5 py-0.5 ${kind === "" ? "bg-muted" : ""}`}>every kind</button>
        {KINDS.filter((k) => items.some((i) => i.kind === k)).map((k) => (
          <button key={k} onClick={() => setKind(k)} className={`text-xs rounded border px-1.5 py-0.5 ${kind === k ? "bg-muted" : ""}`}>{k}</button>
        ))}
      </div>
      <ul className="space-y-1 max-h-[60vh] overflow-y-auto">
        {shown.map((i) => (
          <li key={i.id} className="rounded border px-2 py-1 text-xs flex items-start gap-2">
            <StandingDot standing={i.standing} className="mt-1 shrink-0" />
            <span className="rounded bg-muted px-1 shrink-0">{i.kind}</span>
            <span className="flex-1 min-w-0">
              <span>{i.text}</span>
              {i.sources?.[0] && (
                <span className="text-muted-foreground"> · {i.sources[0].type}
                  {i.sources[0].url && <a href={i.sources[0].url} target="_blank" rel="noreferrer noopener" className="inline-flex ml-1 hover:text-foreground"><ExternalLink className="h-3 w-3" /></a>}
                </span>
              )}
            </span>
          </li>
        ))}
        {shown.length === 0 && <li className="text-xs text-muted-foreground py-4 text-center">Nothing with that standing and kind.</li>}
      </ul>
    </div>
  );
}
