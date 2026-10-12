"use client";

/**
 * The Researcher's studies: one running shows what it is doing; one done shows
 * its dossier — what the reference app is, its surfaces, its screens with
 * screenshots, features with sources, flows, records, rules, what users say,
 * its look, and what could not be seen.
 */
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ExternalLink, Heart, Loader2, Microscope, ThumbsDown, Sparkle, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { FlowCanvas } from "@/components/app-flow/AppFlowPanel";
import { AuthImage } from "./AuthImage";
import { EntityMap } from "./EntityMap";
import { flowsOf } from "./IdeaBoard";
import type { FileMeta, Study } from "./types";

const STATUS: Record<Study["status"], string> = {
  running: "Studying", done: "Done", failed: "Failed", stopped: "Stopped",
};

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h4 className="text-xs font-semibold uppercase text-muted-foreground">
        {title}{count ? ` (${count})` : ""}
      </h4>
      {children}
    </section>
  );
}

function Source({ url }: { url?: string }) {
  if (!url || !/^https?:\/\//.test(url)) return null;
  return (
    <a href={url} target="_blank" rel="noreferrer noopener" className="inline-flex ml-1 text-muted-foreground hover:text-foreground"
      title={url}><ExternalLink className="h-3 w-3" /></a>
  );
}

function Running({ study }: { study: Study }) {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(t);
  }, []);
  const d = study.dossier;
  const found = [["surfaces", d.surfaces], ["screens", d.screens], ["features", d.features], ["rules", d.rules],
    ["voices", d.voices]].filter(([, v]) => (v as unknown[]).length) as [string, unknown[]][];
  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>{study.stage} · {Math.max(0, Math.round((now - study.started) / 60))} min</span>
      </div>
      {found.length > 0 && (
        <p className="text-xs">Found so far: {found.map(([k, v]) => `${v.length} ${k}`).join(", ")}</p>
      )}
      {study.surfaces.length > 0 && (
        <p className="text-xs text-muted-foreground">Studying: {study.surfaces.map((s) => s.name).join(" · ")}</p>
      )}
      <ul className="text-xs space-y-0.5 max-h-80 overflow-y-auto">
        {[...study.steps].reverse().map((s, i) => <li key={i} className="text-muted-foreground">• {s.text}</li>)}
      </ul>
    </div>
  );
}

function Done({ study, filePath, onPicture }:
  { study: Study; filePath: (id: string) => string; onPicture: (f: FileMeta) => void }) {
  const d = study.dossier;
  const flows = useMemo(() => flowsOf(d), [d]);
  const shot = (id?: string) => (id ? study.files.find((f) => f.id === id) : undefined);
  const loose = study.files.filter((f) => !d.screens.some((s) => s.shot === f.id));
  return (
    <div className="space-y-5 text-sm">
      {study.summary && (
        <div className="rounded-lg bg-muted/50 p-3 prose prose-sm max-w-none dark:prose-invert">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{study.summary}</ReactMarkdown>
        </div>
      )}
      {(d.product?.what || d.product?.business) && (
        <Section title="The app">
          <p>{d.product.what}</p>
          {d.product.audience && <p className="text-xs text-muted-foreground">For {d.product.audience}</p>}
          {d.product.business && <p className="text-xs text-muted-foreground">Makes money by {d.product.business}</p>}
        </Section>
      )}
      {d.surfaces.length > 0 && (
        <Section title="Where it was seen" count={d.surfaces.length}>
          <ul className="space-y-0.5">
            {d.surfaces.map((s) => (
              <li key={s.name}>{s.name}<Source url={s.url} />
                {s.reachable === false && <span className="text-xs text-amber-600"> · turned the browser away</span>}
                {s.note && <span className="text-xs text-muted-foreground"> — {s.note}</span>}</li>
            ))}
          </ul>
        </Section>
      )}
      {d.screens.length > 0 && (
        <Section title="Screens" count={d.screens.length}>
          <div className="grid gap-3 sm:grid-cols-2">
            {d.screens.map((s) => {
              const f = shot(s.shot);
              return (
                <div key={s.name} className="rounded-lg border p-2 space-y-1">
                  {f && <AuthImage path={filePath(f.id)} alt={s.name} onClick={() => onPicture(f)}
                    className="h-32 w-full object-cover object-top rounded border cursor-zoom-in" />}
                  <div className="font-medium">{s.name}<Source url={s.url} /></div>
                  {s.purpose && <div className="text-xs">{s.purpose}</div>}
                  {s.shows?.length ? <div className="text-xs text-muted-foreground">Shows: {s.shows.join(", ")}</div> : null}
                  {s.actions?.length ? <div className="text-xs text-muted-foreground">Can: {s.actions.join(", ")}</div> : null}
                </div>
              );
            })}
          </div>
        </Section>
      )}
      {loose.length > 0 && (
        <Section title="More screenshots" count={loose.length}>
          <div className="grid grid-cols-3 gap-2">
            {loose.map((f) => <AuthImage key={f.id} path={filePath(f.id)} alt={f.name} onClick={() => onPicture(f)}
              className="h-24 w-full object-cover object-top rounded border cursor-zoom-in" />)}
          </div>
        </Section>
      )}
      {d.features.length > 0 && (
        <Section title="Features" count={d.features.length}>
          <ul className="space-y-1">
            {d.features.map((f) => (
              <li key={f.name} className="rounded border px-2 py-1">
                <span className="font-medium">{f.name}</span><Source url={f.source} />
                {f.where && <span className="text-xs text-muted-foreground"> · {f.where}</span>}
                {f.detail && <div className="text-xs text-muted-foreground">{f.detail}</div>}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {flows.length > 0 && (
        <Section title="Flows" count={flows.length}>
          <div className="h-[420px] rounded-lg border"><FlowCanvas flows={flows} chosen={null} compact /></div>
        </Section>
      )}
      {d.entities.length > 0 && (
        <Section title="Records it keeps" count={d.entities.length}><EntityMap entities={d.entities} /></Section>
      )}
      {d.rules.length > 0 && (
        <Section title="Rules and policies" count={d.rules.length}>
          <ul className="space-y-0.5 list-disc pl-4">{d.rules.map((r) => <li key={r.text}>{r.text}<Source url={r.source} /></li>)}</ul>
        </Section>
      )}
      {d.voices.length > 0 && (
        <Section title="What users say" count={d.voices.length}>
          <ul className="space-y-1">
            {d.voices.map((v) => (
              <li key={v.text} className="flex gap-2">
                {v.kind === "love" ? <Heart className="h-4 w-4 text-rose-500 shrink-0 mt-0.5" />
                  : v.kind === "hate" ? <ThumbsDown className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
                    : <Sparkle className="h-4 w-4 text-sky-500 shrink-0 mt-0.5" />}
                <span>{v.text}<Source url={v.source} /></span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {d.look && Object.keys(d.look).length > 0 && (
        <Section title="Look">
          {d.look.mood && <p>{d.look.mood}</p>}
          {d.look.palette?.length ? (
            <div className="flex flex-wrap gap-2">
              {d.look.palette.map((c, i) => (
                <div key={i} className="text-xs text-center">
                  <div className="h-8 w-12 rounded border" style={{ background: c.hex }} />
                  <div className="text-muted-foreground">{c.hex}</div>
                </div>
              ))}
            </div>
          ) : null}
          {d.look.fonts?.length ? <p className="text-xs">Type: {d.look.fonts.join(", ")}</p> : null}
          {d.look.layout && <p className="text-xs">{d.look.layout}</p>}
          {d.look.signature?.length ? <p className="text-xs text-muted-foreground">Signature: {d.look.signature.join("; ")}</p> : null}
        </Section>
      )}
      {d.gaps.length > 0 && (
        <Section title="Could not be seen" count={d.gaps.length}>
          <ul className="space-y-0.5">
            {d.gaps.map((g) => <li key={g.text} className="flex gap-2 text-xs"><AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0" />{g.text}</li>)}
          </ul>
        </Section>
      )}
    </div>
  );
}

export function ResearchPanel({ studies, filePath, onPicture }:
  { studies: Study[]; filePath: (id: string) => string; onPicture: (f: FileMeta) => void }) {
  const [chosen, setChosen] = useState<string | null>(null);
  const study = studies.find((s) => s.id === chosen) ?? studies[studies.length - 1];
  if (!study) {
    return (
      <div className="text-sm text-muted-foreground text-center py-8 space-y-2">
        <Microscope className="h-6 w-6 mx-auto" />
        <p>No studies yet. Name an app to learn from and ask Smith to research it — the Researcher studies it in
          the background while you keep talking.</p>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {studies.length > 1 && (
        <div className="flex flex-wrap gap-1">
          {studies.map((s) => (
            <button key={s.id} onClick={() => setChosen(s.id)}
              className={`text-xs rounded-full border px-2 py-0.5 ${s.id === study.id ? "bg-primary text-primary-foreground" : ""}`}>
              {s.reference.slice(0, 30)}
            </button>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <h3 className="font-semibold">{study.reference}</h3>
        <Badge variant={study.status === "done" ? "default" : study.status === "running" ? "secondary" : "destructive"}>
          {STATUS[study.status]}
        </Badge>
      </div>
      {study.focus && <p className="text-xs text-muted-foreground">Looking for: {study.focus}</p>}
      {study.status === "running" && <Running study={study} />}
      {study.status === "done" && <Done study={study} filePath={filePath} onPicture={onPicture} />}
      {(study.status === "failed" || study.status === "stopped") && (
        <>
          <p className="text-sm text-destructive">{study.error}</p>
          <Done study={study} filePath={filePath} onPicture={onPicture} />
        </>
      )}
    </div>
  );
}
