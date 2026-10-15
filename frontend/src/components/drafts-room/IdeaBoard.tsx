"use client";

/**
 * The idea board: what the person and Smith have worked out so far, beside
 * the conversation. Overview (what it is, who for, features, decisions, open
 * questions), Screens (each drawn as a page in the company's brand), Flows
 * (drawn by the App Flow map), Records (drawn),
 * Look, the pictures studied, and — once handed off — the document.
 */
import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ExternalLink, HelpCircle, CheckCircle2, RefreshCw } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FlowCanvas } from "@/components/app-flow/AppFlowPanel";
import type { Flow } from "@/lib/appFlows";
import { AuthImage } from "./AuthImage";
import { EntityMap } from "./EntityMap";
import { ResearchPanel } from "./ResearchPanel";
import { ScreenDrawing } from "./ScreenDrawing";
import { ReferencesPanel } from "./ReferencesPanel";
import { EvidencePanel } from "./EvidencePanel";
import { CardsPanel } from "./CardsPanel";
import { DraftsPanel } from "./DraftsPanel";
import type { Board, Drawing, EvidenceItem, FileMeta, Session } from "./types";

const PRIORITY: Record<string, string> = { must: "First version", should: "Should", later: "Later" };

/** Board or dossier flows, in the App Flow map's shape. */
export function flowsOf(board: Pick<Board, "flows">): Flow[] {
  return (board.flows ?? []).map((f, fi) => {
    const steps = f.steps ?? [];
    return {
      id: `f${fi}`, name: f.name, role: f.role ?? "", goal: f.goal ?? "", ends: steps.at(-1)?.does ?? "",
      nodes: steps.map((s, i) => ({
        id: `s${i}`, page: s.screen, screen: s.screen, route: "", part: "", placement: "",
        last: i === steps.length - 1, ...(i === steps.length - 1 && s.does ? { does: s.does, process: "" } : {}),
      })),
      edges: steps.slice(1).map((_, i) => ({
        from: `s${i}`, to: `s${i + 1}`, does: steps[i].does ?? "", process: "", then: "go" as const,
      })),
    };
  });
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted-foreground py-6 text-center">{children}</p>;
}

export function brandLine(session: Pick<Session, "brand">): string {
  const b = session.brand;
  if (b?.source === "company" && b.company) return `${b.company}'s brand`;
  return b?.source === "board" ? "the board's look" : "a look of Smith's own (no brand on record)";
}

export type StudyActions = {
  addReference: (name: string, url: string) => Promise<void>;
  uploadHar: (rid: string, file: File) => Promise<void>;
  stopStudy: (jid: string) => void;
  fetchEvidence: (jid: string) => Promise<EvidenceItem[]>;
  drawDraft: (did: string) => void;
  pinNote: (did: string, on: string, text: string) => Promise<void>;
  send: (text: string) => void;
  compose: (text: string) => void;
};

export function IdeaBoard({ session, filePath, drawingPath, onPicture, onOpenDrawing, onDraw, tab, onTab, actions }:
  { session: Session; filePath: (id: string) => string; drawingPath: (id: string, kind: "html" | "png") => string;
    onPicture: (f: FileMeta) => void; onOpenDrawing: (d: Drawing) => void; onDraw: (screens?: string[]) => void;
    tab: string; onTab: (tab: string) => void; actions: StudyActions }) {
  const b = session.board;
  const flows = useMemo(() => flowsOf(b), [b]);
  const [chosen, setChosen] = useState<string | null>(null);
  const pictures = session.files ?? [];
  const studies = session.research ?? [];
  const drawings = session.drawings ?? [];
  const references = session.references ?? [];
  const cards = session.cards ?? [];
  const draftsList = session.drafts ?? [];
  const evidenceTotal = studies.reduce((n, st) => n + (st.evidence_total ?? 0), 0);
  const drawingOf = (name: string) => drawings.find((d) => d.screen === name);
  const drawn = (b.screens ?? []).filter((s) => drawingOf(s.name)?.status === "done").length;
  const undrawn = (b.screens ?? []).filter((s) => { const d = drawingOf(s.name); return !d || d.status === "failed" || d.stale; });
  const drawingNow = drawings.some((d) => d.status === "drawing");
  const byPriority = (p: string) => (b.features ?? []).filter((f) => (f.priority ?? "should") === p);

  return (
    <Tabs value={tab} onValueChange={onTab} className="h-full flex flex-col">
      <TabsList variant="line" className="w-full justify-start overflow-x-auto overflow-y-hidden shrink-0">
        <TabsTrigger className="flex-none" value="overview">Overview</TabsTrigger>
        <TabsTrigger className="flex-none" value="references">
          References{references.length ? ` (${references.length})` : ""}
          {studies.some((st) => st.status === "running") && <span className="ml-1 h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />}
        </TabsTrigger>
        <TabsTrigger className="flex-none" value="research">
          Research{studies.length ? ` (${studies.length})` : ""}
        </TabsTrigger>
        <TabsTrigger className="flex-none" value="evidence">Evidence{evidenceTotal ? ` (${evidenceTotal})` : ""}</TabsTrigger>
        <TabsTrigger className="flex-none" value="cards">Cards{cards.length ? ` (${cards.length})` : ""}</TabsTrigger>
        <TabsTrigger className="flex-none" value="drafts">Drafts{draftsList.length ? ` (${draftsList.length})` : ""}</TabsTrigger>
        <TabsTrigger className="flex-none" value="screens">Screens {b.screens?.length ? `(${b.screens.length})` : ""}</TabsTrigger>
        <TabsTrigger className="flex-none" value="flows">Flows {b.flows?.length ? `(${b.flows.length})` : ""}</TabsTrigger>
        <TabsTrigger className="flex-none" value="records">Records {b.entities?.length ? `(${b.entities.length})` : ""}</TabsTrigger>
        <TabsTrigger className="flex-none" value="look">Look</TabsTrigger>
        <TabsTrigger className="flex-none" value="pictures">Pictures {pictures.length ? `(${pictures.length})` : ""}</TabsTrigger>
        {session.handoff && <TabsTrigger className="flex-none" value="document">Document</TabsTrigger>}
      </TabsList>

      <div className="flex-1 overflow-y-auto pt-3">
        <TabsContent value="overview" className="space-y-5 mt-0">
          <section>
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-semibold">{b.product?.name || "Unnamed idea"}</h3>
              <Badge variant={b.status === "agreed" ? "default" : "secondary"}>
                {b.status === "agreed" ? "Agreed" : "Exploring"}
              </Badge>
            </div>
            {b.product?.pitch && <p className="text-sm mt-1">{b.product.pitch}</p>}
            {(b.product?.audience || b.product?.platforms?.length) && (
              <p className="text-xs text-muted-foreground mt-1">
                {[b.product?.audience, b.product?.platforms?.join(", ")].filter(Boolean).join(" · ")}
              </p>
            )}
            {drawn > 0 && (
              <button type="button" className="text-xs text-muted-foreground mt-1 underline-offset-2 hover:underline"
                onClick={() => onTab("screens")}>
                {drawn} screen{drawn === 1 ? "" : "s"} drawn in {brandLine(session)}
              </button>
            )}
          </section>

          {(b.references ?? []).length > 0 && (
            <section>
              <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">Learning from</h4>
              <ul className="space-y-1 text-sm">
                {b.references.map((r) => (
                  <li key={r.name}>
                    <span className="font-medium">{r.name}</span>
                    {r.url && (
                      <a href={r.url} target="_blank" rel="noreferrer noopener"
                        className="inline-flex items-center ml-1 text-muted-foreground hover:text-foreground">
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                    {r.took?.length ? <span className="text-muted-foreground"> — {r.took.join("; ")}</span> : null}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {(b.roles ?? []).length > 0 && (
            <section>
              <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">People</h4>
              <ul className="space-y-1 text-sm">
                {b.roles.map((r) => <li key={r.name}><span className="font-medium">{r.name}</span>
                  {r.does ? <span className="text-muted-foreground"> — {r.does}</span> : null}</li>)}
              </ul>
            </section>
          )}

          <section>
            <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">Features</h4>
            {(b.features ?? []).length === 0 ? <Empty>No features yet.</Empty> : (
              <div className="space-y-3">
                {(["must", "should", "later"] as const).map((p) => byPriority(p).length > 0 && (
                  <div key={p}>
                    <div className="text-xs font-medium mb-1">{PRIORITY[p]}</div>
                    <ul className="space-y-1 text-sm">
                      {byPriority(p).map((f) => (
                        <li key={f.name} className="rounded border px-2 py-1">
                          <span className="font-medium">{f.name}</span>
                          {f.from && <span className="text-xs text-muted-foreground"> · from {f.from}</span>}
                          {f.detail && <div className="text-xs text-muted-foreground">{f.detail}</div>}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </section>

          {(b.questions ?? []).length > 0 && (
            <section>
              <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">Open questions</h4>
              <ul className="space-y-1 text-sm">
                {b.questions.map((q) => (
                  <li key={q.text} className="flex gap-2"><HelpCircle className="h-4 w-4 mt-0.5 text-amber-500 shrink-0" />
                    <span>{q.text}{q.options?.length ? <span className="text-muted-foreground"> ({q.options.join(" / ")})</span> : null}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {(b.decisions ?? []).length > 0 && (
            <section>
              <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">Decided</h4>
              <ul className="space-y-1 text-sm">
                {b.decisions.map((d) => (
                  <li key={d.text} className="flex gap-2"><CheckCircle2 className="h-4 w-4 mt-0.5 text-emerald-600 shrink-0" />
                    <span>{d.text}</span></li>
                ))}
              </ul>
            </section>
          )}
        </TabsContent>

        <TabsContent value="references" className="mt-0">
          <ReferencesPanel references={references} studies={studies} onAdd={actions.addReference}
            onUploadHar={actions.uploadHar} onStop={actions.stopStudy} busy={session.busy} />
        </TabsContent>

        <TabsContent value="evidence" className="mt-0">
          <EvidencePanel studies={studies} references={references} fetchEvidence={actions.fetchEvidence} />
        </TabsContent>

        <TabsContent value="cards" className="mt-0">
          <CardsPanel cards={cards} references={references} />
        </TabsContent>

        <TabsContent value="drafts" className="mt-0">
          <DraftsPanel drafts={draftsList} drawings={drawings} drawingPath={drawingPath} onOpen={actions.drawDraft}
            onDraw={actions.drawDraft} onPin={actions.pinNote} onSend={actions.send} onCompose={actions.compose}
            onOpenDrawing={onOpenDrawing} built={!!session.handoff} />
        </TabsContent>

        <TabsContent value="research" className="mt-0">
          <ResearchPanel studies={studies} filePath={filePath} onPicture={onPicture} />
        </TabsContent>

        <TabsContent value="screens" className="mt-0 space-y-3">
          {(b.screens ?? []).length === 0 ? <Empty>No screens yet.</Empty> : (
            <>
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  {drawn} of {b.screens.length} drawn in {brandLine(session)}
                  {drawingNow && <span className="ml-2 inline-block h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />}
                </span>
                {undrawn.length > 0 && !drawingNow && (
                  <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onDraw()}>
                    <RefreshCw className="h-3 w-3 mr-1" /> Draw {undrawn.length === b.screens.length ? "all" : `${undrawn.length} more`}
                  </Button>
                )}
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                {b.screens.map((s) => {
                  const d = drawingOf(s.name);
                  return (
                    <figure key={s.name} className="text-sm space-y-2">
                      <ScreenDrawing drawing={d} path={drawingPath} onOpen={onOpenDrawing}
                        onRedraw={() => onDraw([s.name])} stale={!!d?.stale} />
                      <figcaption className="space-y-0.5">
                        <div className="font-medium">{s.name}{s.role && <span className="text-xs text-muted-foreground font-normal"> · for {s.role}</span>}</div>
                        {s.purpose && <div className="text-xs text-muted-foreground">{s.purpose}</div>}
                      </figcaption>
                    </figure>
                  );
                })}
              </div>
            </>
          )}
        </TabsContent>

        <TabsContent value="flows" className="mt-0 space-y-2">
          {flows.length === 0 ? <Empty>No flows yet.</Empty> : (
            <>
              <div className="flex flex-wrap gap-1">
                <button onClick={() => setChosen(null)}
                  className={`text-xs rounded-full border px-2 py-0.5 ${chosen === null ? "bg-primary text-primary-foreground" : ""}`}>
                  All
                </button>
                {flows.map((f) => (
                  <button key={f.id} onClick={() => setChosen(f.id)}
                    className={`text-xs rounded-full border px-2 py-0.5 ${chosen === f.id ? "bg-primary text-primary-foreground" : ""}`}>
                    {f.name}
                  </button>
                ))}
              </div>
              {chosen && flows.find((f) => f.id === chosen)?.goal && (
                <p className="text-xs text-muted-foreground">Goal: {flows.find((f) => f.id === chosen)?.goal}</p>
              )}
              <div className="h-[520px] rounded-lg border"><FlowCanvas flows={flows} chosen={chosen} compact /></div>
            </>
          )}
        </TabsContent>

        <TabsContent value="records" className="mt-0"><EntityMap entities={b.entities ?? []} /></TabsContent>

        <TabsContent value="look" className="mt-0 space-y-3 text-sm">
          {!b.look || Object.keys(b.look).length === 0 ? <Empty>Nothing about the look yet.</Empty> : (
            <>
              {b.look.mood && <p><span className="text-muted-foreground">Mood: </span>{b.look.mood}</p>}
              {b.look.palette?.length ? (
                <div className="flex flex-wrap gap-2">
                  {b.look.palette.map((c, i) => (
                    <div key={`${c.hex}-${i}`} className="text-xs text-center">
                      <div className="h-10 w-16 rounded border" style={{ background: c.hex }} />
                      <div>{c.name}</div><div className="text-muted-foreground">{c.hex}</div>
                    </div>
                  ))}
                </div>
              ) : null}
              {b.look.fonts?.length ? <p><span className="text-muted-foreground">Type: </span>{b.look.fonts.join(", ")}</p> : null}
              {b.look.layout && <p><span className="text-muted-foreground">Layout: </span>{b.look.layout}</p>}
              {b.look.avoid && <p><span className="text-muted-foreground">Avoid: </span>{b.look.avoid}</p>}
            </>
          )}
        </TabsContent>

        <TabsContent value="pictures" className="mt-0">
          {pictures.length === 0 ? <Empty>No screenshots or files yet. Drop pictures or PDFs into the conversation.</Empty> : (
            <div className="grid gap-3 grid-cols-2">
              {pictures.map((f) => (
                <figure key={f.id} className="text-xs space-y-1">
                  {f.media_type.startsWith("image/") ? (
                    <AuthImage path={filePath(f.id)} alt={f.name} onClick={() => onPicture(f)}
                      className="h-40 w-full object-cover object-top rounded border cursor-zoom-in" />
                  ) : (
                    <div className="h-40 rounded border flex items-center justify-center text-muted-foreground">PDF</div>
                  )}
                  <figcaption className="truncate" title={f.name}>
                    {f.caption || f.name}
                    <span className="text-muted-foreground"> · {f.origin === "screenshot" ? "Smith" : "you"}</span>
                  </figcaption>
                </figure>
              ))}
            </div>
          )}
        </TabsContent>

        {session.handoff && (
          <TabsContent value="document" className="mt-0 prose prose-sm max-w-none dark:prose-invert">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{session.handoff.document}</ReactMarkdown>
          </TabsContent>
        )}
      </div>
    </Tabs>
  );
}
