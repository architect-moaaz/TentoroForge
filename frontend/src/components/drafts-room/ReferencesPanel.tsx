"use client";

/**
 * What the person pointed at: each reference with its surface study (the
 * Researcher) and its deep study (the browser recording calls and forms),
 * a field to add one by address, and a place to drop a recording of the
 * person's own signed-in session (a HAR file) — stripped of every
 * credential before anything is kept.
 */
import { useRef, useState } from "react";
import { Loader2, Plus, Square, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Reference, Study } from "./types";

const STRIPPED = "Cookies, Authorization and Set-Cookie headers, anything named like a token, and every credential " +
  "secrets-scrub recognises are removed before anything is kept; only the calls' shapes stay. Forge never signs in for you.";

function StudyLine({ study, label, onStop }: { study?: Study; label: string; onStop?: () => void }) {
  if (!study) return <div className="text-xs text-muted-foreground">{label}: not started</div>;
  const counts = study.evidence;
  const total = study.evidence_total ?? 0;
  return (
    <div className="text-xs flex items-center gap-2 flex-wrap">
      <span className="font-medium">{label}</span>
      {study.status === "running" ? (
        <span className="inline-flex items-center gap-1 text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" />{study.stage}</span>
      ) : (
        <span className={study.status === "done" ? "text-emerald-700" : "text-amber-700"}>{study.status}</span>
      )}
      {study.capture && (study.capture.pages > 0 || study.capture.calls > 0) && (
        <span className="text-muted-foreground">{study.capture.pages} pages · {study.capture.calls} calls</span>
      )}
      {total > 0 && counts && <span className="text-muted-foreground">{total} facts ({counts.observed} observed)</span>}
      {study.capture?.stopped_on && <span className="text-muted-foreground">· stopped: {study.capture.stopped_on}</span>}
      {study.status === "running" && study.kind === "deep" && onStop && (
        <button type="button" className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground" onClick={onStop}>
          <Square className="h-3 w-3" /> stop
        </button>
      )}
    </div>
  );
}

export function ReferencesPanel({ references, studies, onAdd, onUploadHar, onStop, busy }:
  { references: Reference[]; studies: Study[]; onAdd: (name: string, url: string) => Promise<void>;
    onUploadHar: (rid: string, file: File) => Promise<void>; onStop: (jid: string) => void; busy?: boolean }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const fileFor = useRef<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const studyOf = (id?: string) => (id ? studies.find((s) => s.id === id) : undefined);

  const add = async () => {
    if (!name.trim() || !url.trim()) return;
    setAdding(true); setError(null);
    try { await onAdd(name.trim(), url.trim()); setName(""); setUrl(""); }
    catch (e) { setError(e instanceof Error ? e.message : "That reference could not be added"); }
    finally { setAdding(false); }
  };
  const pick = (rid: string) => { fileFor.current = rid; input.current?.click(); };
  const chosen = async (files: FileList | null) => {
    const rid = fileFor.current; const f = files?.[0];
    if (!rid || !f) return;
    setUploading(rid); setError(null);
    try { await onUploadHar(rid, f); }
    catch (e) { setError(e instanceof Error ? e.message : "That recording could not be read"); }
    finally { setUploading(null); if (input.current) input.current.value = ""; }
  };

  return (
    <div className="space-y-4 text-sm">
      <input ref={input} type="file" accept=".har,application/json" className="hidden" onChange={(e) => void chosen(e.target.files)} />
      {references.length === 0 && (
        <p className="text-muted-foreground">No references yet. Name a product and its address: the Researcher reads its public
          pages while the deep study walks its screens and records what it does.</p>
      )}
      <ul className="space-y-3">
        {references.map((r) => (
          <li key={r.id} className="rounded-lg border p-3 space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <div className="font-medium truncate">{r.name}
                {r.url && <a href={r.url} target="_blank" rel="noreferrer noopener" className="ml-2 text-xs text-muted-foreground underline-offset-2 hover:underline">{r.url.replace(/^https?:\/\//, "")}</a>}
              </div>
              <Button size="sm" variant="outline" className="h-7 text-xs shrink-0" disabled={uploading === r.id || busy}
                onClick={() => pick(r.id)} title={STRIPPED}>
                {uploading === r.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
                <span className="ml-1">{r.har ? "Another recording" : "Drop your recording (HAR)"}</span>
              </Button>
            </div>
            <StudyLine label="Surface" study={studyOf(r.studies?.surface)} />
            <StudyLine label="Deep" study={studyOf(r.studies?.deep)} onStop={() => r.studies?.deep && onStop(r.studies.deep)} />
            {r.har && <StudyLine label="Your recording" study={studyOf(r.studies?.har)} />}
          </li>
        ))}
      </ul>
      <div className="rounded-lg border p-3 space-y-2">
        <div className="text-xs font-semibold uppercase text-muted-foreground">Add a reference</div>
        <div className="flex gap-2">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Product" className="h-8 w-1/3 rounded border bg-background px-2 text-sm" />
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" className="h-8 flex-1 rounded border bg-background px-2 text-sm"
            onKeyDown={(e) => { if (e.key === "Enter") void add(); }} />
          <Button size="sm" className="h-8" disabled={adding || busy || !name.trim() || !url.trim()} onClick={() => void add()}>
            {adding ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}<span className="ml-1">Add</span>
          </Button>
        </div>
        <p className="text-xs text-muted-foreground" data-testid="har-note">{STRIPPED}</p>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
    </div>
  );
}
