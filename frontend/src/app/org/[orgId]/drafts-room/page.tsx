"use client";

/**
 * The Drafts Room — Smith and the person work an idea out before any app exists.
 *
 * Sessions on the left; the conversation in the middle, where pictures and
 * PDFs can be dropped in and Smith's research shows as he does it; the idea
 * board on the right, where each screen is drawn as a page in the company's
 * brand as it lands. When they agree and the person says to build, Smith
 * hands the idea over: the app is created, its build starts on the platform
 * from the requirements document (the drawings go with it as design
 * references), and this page moves to it.
 */
import { use, useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  PencilRuler, Hammer, ImagePlus, Loader2, Paperclip, Plus, Send, Trash2, X, FileText, ArrowRight, Microscope,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { AuthImage } from "@/components/drafts-room/AuthImage";
import { DrawingFrame, VIEWPORTS } from "@/components/drafts-room/ScreenDrawing";
import { IdeaBoard, type StudyActions } from "@/components/drafts-room/IdeaBoard";
import { useDraftsRoomTurn, type Handoff } from "@/components/drafts-room/useDraftsRoomTurn";
import type { Card, ChatEntry, Draft, Drawing, EvidenceItem, FileMeta, Reference, Session, SessionRow, Study } from "@/components/drafts-room/types";

const OPENERS = [
  "I want to build an app like a well-known one — research it with me",
  "I have an idea for an app and want to shape it",
  "Here are screenshots of an app I like — let's work out what to build",
];

function DraftsRoomPage({ orgId }: { orgId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<FileMeta[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [picture, setPicture] = useState<FileMeta | null>(null);
  const [shown, setShown] = useState<Drawing | null>(null);
  const [handingOff, setHandingOff] = useState<Handoff | null>(null);
  const [boardTab, setBoardTab] = useState("overview");
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const base = `/api/orgs/${orgId}/drafts-room`;
  // THE LOADED SESSION'S, NOT THE SELECTED ONE'S: between choosing a session
  // and its arrival, the old one's pictures are still on screen.
  const filePath = useCallback((fid: string) => `${base}/${session?.id}/files/${fid}`, [base, session?.id]);
  const drawingPath = useCallback((id: string, kind: "html" | "png") => `${base}/${session?.id}/drawings/${id}.${kind}`,
    [base, session?.id]);

  const { data: sessions = [] } = useQuery({
    queryKey: ["org", orgId, "drafts-room"],
    queryFn: () => api.get<SessionRow[]>(base),
  });

  useEffect(() => {
    setBoardTab("overview");
    if (!activeId) { setSession(null); return; }
    let gone = false;
    api.get<Session>(`${base}/${activeId}`).then((s) => { if (!gone) setSession(s); }).catch(() => undefined);
    return () => { gone = true; };
  }, [activeId, base]);

  const onHandoff = useCallback((h: Handoff) => {
    // The platform has already created the app and started its build; the
    // project page reattaches to the running build when it opens. Nothing is
    // replayed from the browser, so the build runs even if nobody arrives.
    setHandingOff(h);
    queryClient.invalidateQueries({ queryKey: ["org", orgId, "drafts-room"] });
    window.setTimeout(() => router.push(`/org/${orgId}/projects/${h.project_id}`), 1200);
  }, [orgId, queryClient, router]);

  const putStudy = useCallback((study: Study) => setSession((s) => {
    if (!s) return s;
    const rest = (s.research ?? []).filter((r) => r.id !== study.id);
    return { ...s, research: [...rest, study].sort((a, b) => a.started - b.started) };
  }), []);

  const putDrawing = useCallback((d: Drawing) => setSession((s) => {
    if (!s) return s;
    const rest = (s.drawings ?? []).filter((r) => r.screen !== d.screen || (r.scope ?? "board") !== (d.scope ?? "board"));
    return { ...s, drawings: [...rest, d] };
  }), []);
  const putReference = useCallback((r: Reference) => setSession((s) => (s
    ? { ...s, references: [...(s.references ?? []).filter((x) => x.id !== r.id), r] } : s)), []);
  const putDraft = useCallback((d: Draft) => setSession((s) => (s
    ? { ...s, drafts: [...(s.drafts ?? []).filter((x) => x.id !== d.id), { ...d, versions: [...((s.drafts ?? []).find((x) => x.id === d.id)?.versions ?? []).filter((v) => v.version !== d.version), { version: d.version, at: d.at, changed: d.changed }] }] } : s)), []);

  // A STUDY OR A DRAWING RUNS WHILE THE CONVERSATION GOES ON: while one is
  // running, its progress is read every few seconds — the studies and the
  // drawings only, never the chat, which the turn in flight owns.
  const running = (session?.research ?? []).some((r) => r.status === "running")
    || (session?.drawings ?? []).some((d) => d.status === "drawing");
  useEffect(() => {
    if (!running || !session) return;
    const id = session.id;
    const t = window.setInterval(() => {
      api.get<Session>(`${base}/${id}`)
        .then((fresh) => setSession((s) => (s && s.id === id
          ? { ...s, research: fresh.research, drawings: fresh.drawings, brand: fresh.brand, references: fresh.references,
              cards: fresh.cards, drafts: fresh.drafts } : s)))
        .catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(t);
  }, [running, session?.id, base]);

  // The study side's actions, all on the session's routes; the drafting
  // side's (revise, build) go through the conversation so Smith does them.
  const actions: StudyActions = {
    addReference: async (name, url) => {
      if (!session) return;
      const id = session.id;
      const refs = await api.post<Reference[]>(`${base}/${id}/references`, { name, url });
      const fresh = await api.get<Session>(`${base}/${id}`);
      setSession((s) => (s && s.id === id ? { ...s, references: refs, research: fresh.research, chat: fresh.chat } : s));
    },
    uploadHar: async (rid, file) => {
      if (!session) return;
      const id = session.id;
      const form = new FormData();
      form.append("file", file);
      await api.upload<{ reference: Reference }>(`${base}/${id}/references/${rid}/har`, form);
      const fresh = await api.get<Session>(`${base}/${id}`);
      setSession((s) => (s && s.id === id ? { ...s, references: fresh.references, research: fresh.research, cards: fresh.cards } : s));
    },
    stopStudy: (jid) => { if (session) void api.post(`${base}/${session.id}/studies/${jid}/stop`, {}); },
    fetchEvidence: useCallback((jid: string) => (session
      ? api.get<EvidenceItem[]>(`${base}/${session.id}/studies/${jid}/evidence`) : Promise.resolve([])), [base, session?.id]),
    drawDraft: (did) => {
      if (!session) return;
      const id = session.id;
      api.post<Drawing[]>(`${base}/${id}/drafts/${did}/draw`, {})
        .then((rows) => setSession((s) => (s && s.id === id
          ? { ...s, drawings: [...(s.drawings ?? []).filter((r) => r.scope !== `draft:${did}`), ...rows] } : s)))
        .catch(() => undefined);
    },
    pinNote: async (did, on, text) => {
      if (!session) return;
      const latest = await api.post<Draft>(`${base}/${session.id}/drafts/${did}/notes`, { on, text });
      putDraft(latest);
    },
    send: (text) => send(text),
    compose: (text) => setDraft(text),
  };

  const draw = async (screens?: string[]) => {
    if (!session) return;
    const id = session.id;
    try {
      const rows = await api.post<Drawing[]>(`${base}/${id}/draw`, { screens: screens ?? [], note: "" });
      setSession((s) => (s && s.id === id ? { ...s, drawings: rows } : s));
      setBoardTab("screens");
    } catch {
      /* the card keeps its state; the person can try again */
    }
  };

  const turn = useDraftsRoomTurn(orgId, activeId, {
    onBoard: (board) => setSession((s) => (s ? { ...s, board } : s)),
    onFile: (file) => setSession((s) => (s ? { ...s, files: [...(s.files ?? []), file] } : s)),
    onMessage: (entry) => setSession((s) => (s ? { ...s, chat: [...s.chat, entry] } : s)),
    onHandoff,
    onStudy: (study) => { putStudy(study); if (study.status === "running") setBoardTab("research"); },
    onDrawing: putDrawing,
    onReference: (r) => { putReference(r); setBoardTab("references"); },
    onCards: (cards: Card[]) => setSession((s) => (s ? { ...s, cards } : s)),
    onDraft: (d) => { putDraft(d); setBoardTab("drafts"); },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.chat.length, turn.live, turn.steps.length]);

  const startNew = async (text?: string) => {
    // An idea not yet started is the one to start: no pile of empty sessions.
    const empty = sessions.find((r) => r.messages === 0 && !r.project_id);
    const s = empty ? await api.get<Session>(`${base}/${empty.id}`) : await api.post<Session>(base, { title: "" });
    queryClient.invalidateQueries({ queryKey: ["org", orgId, "drafts-room"] });
    setActiveId(s.id);
    setSession(s);
    if (text) setDraft(text);
  };

  const remove = async (id: string) => {
    if (!window.confirm("Delete this Drafts Room session? Its conversation, board and pictures go with it.")) return;
    await api.delete(`${base}/${id}`);
    if (id === activeId) setActiveId(null);
    queryClient.invalidateQueries({ queryKey: ["org", orgId, "drafts-room"] });
  };

  const upload = async (files: FileList | File[]) => {
    if (!activeId) return;
    setUploading(true);
    setUploadError(null);
    try {
      for (const f of Array.from(files)) {
        const form = new FormData();
        form.append("file", f);
        const meta = await api.upload<FileMeta>(`${base}/${activeId}/files`, form);
        setPending((p) => [...p, meta]);
        setSession((s) => (s ? { ...s, files: [...(s.files ?? []), meta] } : s));
      }
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "That file could not be added");
    } finally {
      setUploading(false);
    }
  };

  const send = (text?: string) => {
    const words = (text ?? draft).trim();
    if (!words || !session || turn.busy) return;
    const files = pending.map((f) => f.id);
    setSession({ ...session, chat: [...session.chat, { role: "user", text: words, files, at: Date.now() / 1000 }] });
    setDraft("");
    setPending([]);
    void turn.send(words, files).then(() =>
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "drafts-room"] }));
  };

  const fileOf = (id: string) => session?.files?.find((f) => f.id === id);
  const canBuild = !!session && !session.handoff && (session.board?.features?.length ?? 0) > 0;

  return (
    <div className="flex h-screen">
      {/* Sessions */}
      <aside className="w-60 shrink-0 border-r flex flex-col">
        <div className="p-3 border-b flex items-center gap-2">
          <PencilRuler className="h-5 w-5 text-primary" />
          <span className="font-semibold">Drafts Room</span>
        </div>
        <div className="p-3">
          <Button className="w-full" size="sm" onClick={() => void startNew()}>
            <Plus className="h-4 w-4 mr-1" /> New idea
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto px-2 space-y-1">
          {sessions.map((s) => (
            <div key={s.id}
              className={`group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm cursor-pointer hover:bg-muted ${s.id === activeId ? "bg-muted" : ""}`}
              onClick={() => setActiveId(s.id)}>
              <span className="flex-1 truncate" title={s.title}>{s.title}</span>
              {s.project_id && <Hammer className="h-3.5 w-3.5 text-emerald-600 shrink-0" aria-label="Handed to an app" />}
              <button className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
                onClick={(e) => { e.stopPropagation(); void remove(s.id); }} aria-label="Delete session">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      </aside>

      {!session ? (
        <main className="flex-1 flex items-center justify-center p-8">
          <div className="max-w-lg text-center space-y-4">
            <PencilRuler className="h-10 w-10 mx-auto text-primary" />
            <h1 className="text-2xl font-semibold">The Drafts Room</h1>
            <p className="text-muted-foreground">
              Work an app idea out with Smith before anything is built. Name an app to learn from and he researches
              it — features, screens, flows, records and look — and shows you what he finds. Drop in screenshots or
              PDFs. When you agree, he writes the requirements and starts the build.
            </p>
            <div className="space-y-2">
              {OPENERS.map((o) => (
                <button key={o} onClick={() => void startNew(o)}
                  className="w-full text-left rounded-lg border px-3 py-2 text-sm hover:bg-muted">{o}</button>
              ))}
            </div>
          </div>
        </main>
      ) : (
        <>
          {/* Conversation */}
          <main className="flex-1 min-w-0 flex flex-col"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files.length) void upload(e.dataTransfer.files); }}>
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {session.chat.length === 0 && (
                <p className="text-sm text-muted-foreground text-center mt-10">
                  Tell Smith what you want to build — or which app you want to learn from.
                </p>
              )}
              {session.chat.map((m, i) => (
                <Bubble key={i} entry={m} fileOf={fileOf} filePath={filePath} onPicture={setPicture}
                  onOpen={(pid) => router.push(`/org/${orgId}/projects/${pid}`)} />
              ))}
              {turn.busy && (
                <div className="space-y-2">
                  {turn.steps.length > 0 && (
                    <ul className="text-xs text-muted-foreground space-y-0.5">
                      {turn.steps.map((s, i) => <li key={i}>• {s}</li>)}
                    </ul>
                  )}
                  <div className="rounded-lg bg-muted/60 px-3 py-2 text-sm max-w-[85%]">
                    {turn.live ? (
                      <div className="prose prose-sm max-w-none dark:prose-invert">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.live}</ReactMarkdown>
                      </div>
                    ) : (
                      <span className="inline-flex items-center gap-2 text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" /> Smith is thinking…
                      </span>
                    )}
                  </div>
                </div>
              )}
              {turn.error && <p className="text-sm text-destructive">{turn.error}</p>}
              {!turn.busy && (session.research ?? []).filter((r) => r.status === "done" && !r.read).map((r) => (
                <div key={r.id} className="rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-sm flex items-center gap-2 flex-wrap">
                  <Microscope className="h-4 w-4 text-sky-600" />
                  <span className="flex-1">The Researcher has finished studying {r.reference}.</span>
                  <Button size="sm" variant="outline" onClick={() => setBoardTab("research")}>See the study</Button>
                  <Button size="sm" onClick={() => send(`The study of ${r.reference} is ready — walk me through what it found.`)}>
                    Walk me through it
                  </Button>
                </div>
              ))}
              {handingOff && handingOff.build === "started" && (
                <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" /> Building {handingOff.app_name}…{" "}
                  <Link href={`/org/${orgId}/projects/${handingOff.project_id}`} className="underline">open it</Link>
                </div>
              )}
              {handingOff && handingOff.build === "not_started" && (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
                  Created {handingOff.app_name}; its build did not start — {" "}
                  <Link href={`/org/${orgId}/projects/${handingOff.project_id}`} className="underline">open it</Link> and ask Smith to build.
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            <div className="border-t p-3 space-y-2">
              {(pending.length > 0 || uploading || uploadError) && (
                <div className="flex flex-wrap gap-2 items-center">
                  {pending.map((f) => (
                    <span key={f.id} className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs">
                      {f.media_type === "application/pdf" ? <FileText className="h-3 w-3" /> : <ImagePlus className="h-3 w-3" />}
                      <span className="max-w-[10rem] truncate">{f.name}</span>
                      <button onClick={() => setPending((p) => p.filter((x) => x.id !== f.id))} aria-label="Remove">
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                  {uploading && <Loader2 className="h-4 w-4 animate-spin" />}
                  {uploadError && <span className="text-xs text-destructive">{uploadError}</span>}
                </div>
              )}
              <div className="flex gap-2 items-end">
                <input ref={fileInput} type="file" multiple accept="image/png,image/jpeg,image/webp,image/gif,application/pdf"
                  className="hidden" onChange={(e) => { if (e.target.files) void upload(e.target.files); e.target.value = ""; }} />
                <Button variant="ghost" size="icon" onClick={() => fileInput.current?.click()} disabled={turn.busy}
                  aria-label="Add pictures or a PDF"><Paperclip className="h-4 w-4" /></Button>
                <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={2}
                  placeholder="Talk it through with Smith — or drop screenshots here"
                  className="flex-1 resize-none rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                  disabled={!!session.handoff} />
                <Button onClick={() => send()} disabled={turn.busy || !draft.trim() || !!session.handoff} aria-label="Send">
                  {turn.busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </Button>
              </div>
              {canBuild && (
                <div className="flex justify-end">
                  <Button variant="outline" size="sm" disabled={turn.busy} onClick={() => send("Build it")}>
                    <Hammer className="h-4 w-4 mr-1" /> Build this app
                  </Button>
                </div>
              )}
              {session.handoff && (
                <div className="flex justify-end">
                  <Button size="sm" onClick={() => router.push(`/org/${orgId}/projects/${session.handoff!.project_id}`)}>
                    Open {session.handoff.app_name} <ArrowRight className="h-4 w-4 ml-1" />
                  </Button>
                </div>
              )}
            </div>
          </main>

          {/* Idea board */}
          <aside className="w-[42%] max-w-[720px] shrink-0 border-l p-4 overflow-hidden">
            <IdeaBoard session={session} filePath={filePath} drawingPath={drawingPath} onPicture={setPicture}
              onOpenDrawing={setShown} onDraw={draw} tab={boardTab} onTab={setBoardTab} actions={actions} />
          </aside>
        </>
      )}

      <Dialog open={!!shown} onOpenChange={(o) => { if (!o) setShown(null); }}>
        <DialogContent className="sm:max-w-[min(96vw,1360px)]">
          <DialogTitle className="text-sm">{shown?.caption || shown?.screen}</DialogTitle>
          {shown && session && (
            <div className="max-h-[80vh] overflow-auto flex gap-4 items-start">
              <div className="shrink-0 border rounded-md overflow-hidden bg-white">
                <DrawingFrame drawing={shown} path={drawingPath} live
                  width={Math.min(VIEWPORTS[shown.viewport].w, shown.viewport === "phone" ? 390 : 1100)} />
              </div>
              {shown.like && session.files?.some((f) => f.id === shown.like) && (
                <figure className="w-56 shrink-0 text-xs text-muted-foreground space-y-1">
                  <AuthImage path={filePath(shown.like)} alt="modelled on" className="w-full rounded border" />
                  <figcaption>Modelled on this screenshot — its layout only, none of its wording, logo, pictures or colours.</figcaption>
                </figure>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!picture} onOpenChange={(o) => { if (!o) setPicture(null); }}>
        <DialogContent className="max-w-5xl">
          <DialogTitle className="text-sm">{picture?.caption || picture?.name}</DialogTitle>
          {picture && (
            <div className="max-h-[75vh] overflow-auto">
              <AuthImage path={filePath(picture.id)} alt={picture.name} className="w-full" />
            </div>
          )}
          {picture?.source && (
            <a href={picture.source} target="_blank" rel="noreferrer noopener" className="text-xs text-muted-foreground underline">
              {picture.source}
            </a>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Bubble({ entry, fileOf, filePath, onPicture, onOpen }: {
  entry: ChatEntry;
  fileOf: (id: string) => FileMeta | undefined;
  filePath: (id: string) => string;
  onPicture: (f: FileMeta) => void;
  onOpen: (projectId: string) => void;
}) {
  const mine = entry.role === "user";
  const files = (entry.files ?? []).map(fileOf).filter(Boolean) as FileMeta[];
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[85%] space-y-2 ${mine ? "items-end" : ""}`}>
        {!mine && (entry.steps?.length ?? 0) > 0 && (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">What Smith did ({entry.steps!.length})</summary>
            <ul className="mt-1 space-y-0.5">{entry.steps!.map((s, i) => <li key={i}>• {s}</li>)}</ul>
          </details>
        )}
        {entry.text && (
          <div className={`rounded-lg px-3 py-2 text-sm ${mine ? "bg-primary text-primary-foreground" : "bg-muted/60"}`}>
            {mine ? <p className="whitespace-pre-wrap">{entry.text}</p> : (
              <div className="prose prose-sm max-w-none dark:prose-invert">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{entry.text}</ReactMarkdown>
              </div>
            )}
          </div>
        )}
        {files.length > 0 && (
          <div className="grid grid-cols-2 gap-2">
            {files.map((f) => f.media_type.startsWith("image/") ? (
              <AuthImage key={f.id} path={filePath(f.id)} alt={f.name} onClick={() => onPicture(f)}
                className="h-36 w-full object-cover object-top rounded border cursor-zoom-in" />
            ) : (
              <span key={f.id} className="inline-flex items-center gap-1 rounded border px-2 py-1 text-xs">
                <FileText className="h-3 w-3" /> {f.name}
              </span>
            ))}
          </div>
        )}
        {entry.handoff && (
          <Button size="sm" onClick={() => onOpen(entry.handoff!.project_id)}>
            Open {entry.handoff.app_name} <ArrowRight className="h-4 w-4 ml-1" />
          </Button>
        )}
      </div>
    </div>
  );
}

export default function DraftsRoomPageWrapper({ params }: { params: Promise<{ orgId: string }> }) {
  const { orgId } = use(params);
  return <DraftsRoomPage orgId={orgId} />;
}
