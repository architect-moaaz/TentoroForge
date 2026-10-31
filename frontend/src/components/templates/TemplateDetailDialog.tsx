"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Copy,
  FlaskConical,
  Loader2,
  Send,
  ShieldCheck,
  Trash2,
  Users,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  STATUS_LABEL,
  countsLine,
  formatDate,
  type TemplateDetailData,
  type TemplateReviewData,
} from "@/lib/templateGallery";
import { PersonAvatar, PriceBadge, Shot, StarInput, Stars, StatusBadge } from "./TemplateBits";

/**
 * One template, all of it: what it looks like, what it holds, who built it,
 * what people thought of it — and, for its builder and for Tentoro, where its
 * review stands and what to do next.
 */
export function TemplateDetailDialog({
  templateId,
  orgId,
  open,
  onOpenChange,
  onOpenCreator,
  onSubmit,
}: {
  templateId: string | null;
  /** The organisation a "Use" makes the new app in. Without one, the person's first. */
  orgId?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenCreator?: (userId: string) => void;
  onSubmit?: (templateId: string) => void;
}) {
  const queryClient = useQueryClient();
  const { data: tpl, isLoading, isError } = useQuery({
    queryKey: ["project-template", templateId, "detail"],
    queryFn: () => api.get<TemplateDetailData>(`/api/project-templates/${templateId}/detail`),
    enabled: open && !!templateId,
  });
  const [shot, setShot] = useState(0);
  useEffect(() => setShot(0), [templateId]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["project-template", templateId] });
    queryClient.invalidateQueries({ queryKey: ["project-templates"] });
    queryClient.invalidateQueries({ queryKey: ["template-gallery"] });
    queryClient.invalidateQueries({ queryKey: ["template-requests"] });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-4xl">
        {isLoading || !tpl ? (
          <>
            <DialogHeader>
              <DialogTitle>Template</DialogTitle>
              <DialogDescription>{isError ? "This template is not available." : "Loading…"}</DialogDescription>
            </DialogHeader>
            {!isError && (
              <div className="flex justify-center py-16">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            )}
          </>
        ) : (
          <>
            <DialogHeader>
              <div className="flex flex-wrap items-center gap-2">
                <DialogTitle className="text-xl">{tpl.name}</DialogTitle>
                <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                  v{tpl.version}
                </span>
                {(tpl.can_manage || tpl.is_admin || tpl.status !== "approved") && <StatusBadge status={tpl.status} />}
                {tpl.category && (
                  <span className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">{tpl.category}</span>
                )}
                <PriceBadge pricing={tpl.pricing} />
              </div>
              <DialogDescription asChild>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-xs text-muted-foreground">
                  {tpl.creator && (
                    <button
                      type="button"
                      onClick={() => tpl.creator?.id && onOpenCreator?.(tpl.creator.id)}
                      disabled={!onOpenCreator || (tpl.status !== "approved" && !tpl.is_admin)}
                      className="inline-flex items-center gap-1.5 font-medium text-foreground enabled:hover:underline"
                    >
                      <PersonAvatar person={tpl.creator} className="h-5 w-5" />
                      {tpl.creator.name}
                    </button>
                  )}
                  {tpl.org_name && <span>{tpl.org_name}</span>}
                  <span>Built {formatDate(tpl.created_at)}</span>
                  {tpl.published_at && <span>Published {formatDate(tpl.published_at)}</span>}
                  <span className="inline-flex items-center gap-1">
                    <Users className="h-3 w-3" /> Used {tpl.uses} time{tpl.uses === 1 ? "" : "s"}
                  </span>
                  <Stars value={tpl.rating} count={tpl.ratings} />
                </div>
              </DialogDescription>
            </DialogHeader>

            <div className="grid gap-5 lg:grid-cols-[1fr_280px]">
              <div className="min-w-0 space-y-4">
                <Carousel tpl={tpl} index={shot} onIndex={setShot} />
                <Tabs defaultValue="overview">
                  <TabsList className="w-full justify-start overflow-x-auto [scrollbar-width:none]">
                    <TabsTrigger className="px-2 text-xs" value="overview">Overview</TabsTrigger>
                    <TabsTrigger className="px-2 text-xs" value="screens">Screens ({tpl.preview?.screens.length ?? 0})</TabsTrigger>
                    <TabsTrigger className="px-2 text-xs" value="data" title="Data models">Data ({tpl.preview?.records.length ?? 0})</TabsTrigger>
                    <TabsTrigger className="px-2 text-xs" value="workflows">Workflows ({tpl.preview?.workflows.length ?? 0})</TabsTrigger>
                    <TabsTrigger className="px-2 text-xs" value="rules">Rules ({tpl.preview?.rules.length ?? 0})</TabsTrigger>
                    <TabsTrigger className="px-2 text-xs" value="reviews">Reviews ({tpl.ratings})</TabsTrigger>
                  </TabsList>
                  <TabsContent value="overview" className="space-y-4 pt-2">
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">{tpl.description || "No description."}</p>
                    {countsLine(tpl.summary.counts) && (
                      <p className="text-sm text-foreground/80">{countsLine(tpl.summary.counts)}</p>
                    )}
                    {!!tpl.summary.palette?.length && (
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs text-muted-foreground">Colours</span>
                        {tpl.summary.palette.map((c) => (
                          <span key={c} title={c} className="h-4 w-7 rounded-sm border" style={{ backgroundColor: c }} />
                        ))}
                      </div>
                    )}
                    {!!tpl.preview?.roles.length && (
                      <div>
                        <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Who uses it</h4>
                        <ul className="space-y-1 text-sm">
                          {tpl.preview.roles.map((r) => (
                            <li key={r.name}>
                              <span className="font-medium">{r.name}</span>
                              {r.description && <span className="text-muted-foreground"> — {r.description}</span>}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </TabsContent>
                  <TabsContent value="screens" className="pt-2">
                    <ul className="divide-y rounded-lg border">
                      {tpl.preview?.screens.map((s) => (
                        <li key={s.route + s.name} className="p-3">
                          <div className="flex flex-wrap items-baseline gap-2">
                            <span className="text-sm font-medium">{s.name}</span>
                            <code className="text-[11px] text-muted-foreground">{s.route}</code>
                            {s.who.length > 0 && <span className="text-[11px] text-muted-foreground">· {s.who.join(", ")}</span>}
                          </div>
                          {s.purpose && <p className="mt-1 text-xs text-muted-foreground">{s.purpose}</p>}
                        </li>
                      ))}
                    </ul>
                  </TabsContent>
                  <TabsContent value="data" className="space-y-3 pt-2">
                    {tpl.preview?.records.map((r) => (
                      <div key={r.name} className="rounded-lg border">
                        <div className="border-b bg-muted/40 px-3 py-2">
                          <p className="text-sm font-medium">{r.name}</p>
                          {r.description && <p className="text-xs text-muted-foreground">{r.description}</p>}
                        </div>
                        <table className="w-full text-xs">
                          <tbody>
                            {r.fields.map((f) => (
                              <tr key={f.name} className="border-b last:border-0">
                                <td className="px-3 py-1.5 font-mono">{f.name}{f.required && <span className="text-rose-600">*</span>}</td>
                                <td className="px-3 py-1.5 text-muted-foreground">
                                  {f.choices?.length ? <>one of <span className="text-foreground">{f.choices.join(", ")}</span></> : f.type}
                                </td>
                                <td className="hidden px-3 py-1.5 text-muted-foreground sm:table-cell">{f.description}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ))}
                  </TabsContent>
                  <TabsContent value="workflows" className="space-y-3 pt-2">
                    {tpl.preview?.workflows.map((w) => (
                      <div key={w.name} className="rounded-lg border p-3">
                        <p className="text-sm font-medium">{w.name}</p>
                        {w.purpose && <p className="text-xs text-muted-foreground">{w.purpose}</p>}
                        {w.trigger && <p className="mt-1 text-xs"><span className="text-muted-foreground">Starts when: </span>{w.trigger}</p>}
                        {w.steps.length > 0 && (
                          <ol className="mt-2 flex flex-wrap items-center gap-1 text-[11px]">
                            {w.steps.map((st, i) => (
                              <li key={i} className="flex items-center gap-1">
                                <span className="rounded bg-muted px-1.5 py-0.5">{st}</span>
                                {i < w.steps.length - 1 && <ChevronRight className="h-3 w-3 text-muted-foreground" />}
                              </li>
                            ))}
                          </ol>
                        )}
                      </div>
                    ))}
                  </TabsContent>
                  <TabsContent value="rules" className="pt-2">
                    <ul className="space-y-2">
                      {tpl.preview?.rules.map((r) => (
                        <li key={r.name} className="rounded-lg border p-3 text-sm">
                          <span className="font-medium">{r.name}</span>
                          {r.record && <span className="text-xs text-muted-foreground"> · {r.record}</span>}
                          <p className="mt-0.5 text-xs text-muted-foreground">{r.statement}</p>
                        </li>
                      ))}
                    </ul>
                  </TabsContent>
                  <TabsContent value="reviews" className="pt-2">
                    <Reviews tpl={tpl} onChanged={refresh} />
                  </TabsContent>
                </Tabs>
              </div>

              <aside className="space-y-4">
                {tpl.can_use && <UsePanel tpl={tpl} orgId={orgId} />}
                {(tpl.can_manage || tpl.is_admin) && (
                  <ReviewState tpl={tpl} onChanged={refresh} onSubmit={onSubmit} />
                )}
                {tpl.is_admin && <AdminPanel tpl={tpl} onChanged={refresh} />}
              </aside>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Carousel({ tpl, index, onIndex }: { tpl: TemplateDetailData; index: number; onIndex: (i: number) => void }) {
  const shots = tpl.screenshots;
  if (!shots.length) {
    return (
      <div className="flex aspect-[16/9] items-center justify-center rounded-lg border bg-muted text-sm text-muted-foreground">
        No screenshots
      </div>
    );
  }
  const i = Math.min(index, shots.length - 1);
  return (
    <div className="space-y-2">
      <div className="relative overflow-hidden rounded-lg border bg-muted">
        <Shot templateId={tpl.id} shotId={shots[i].id} alt={shots[i].caption || `${tpl.name} screenshot ${i + 1}`} className="aspect-[16/9] w-full" />
        {shots.length > 1 && (
          <>
            <button type="button" aria-label="Previous screenshot" onClick={() => onIndex((i - 1 + shots.length) % shots.length)} className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-black/60 p-1.5 text-white hover:bg-black/80">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button type="button" aria-label="Next screenshot" onClick={() => onIndex((i + 1) % shots.length)} className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-black/60 p-1.5 text-white hover:bg-black/80">
              <ChevronRight className="h-4 w-4" />
            </button>
          </>
        )}
        {shots[i].caption && (
          <span className="absolute bottom-2 left-2 rounded bg-black/60 px-2 py-0.5 text-[11px] text-white">{shots[i].caption}</span>
        )}
      </div>
      {shots.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {shots.map((s, j) => (
            <button
              key={s.id}
              type="button"
              onClick={() => onIndex(j)}
              aria-label={`Screenshot ${j + 1}`}
              aria-current={j === i}
              className={cn("shrink-0 overflow-hidden rounded border-2", j === i ? "border-brand-900" : "border-transparent opacity-70 hover:opacity-100")}
            >
              <Shot templateId={tpl.id} shotId={s.id} alt="" className="h-12 w-20" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function UsePanel({ tpl, orgId }: { tpl: TemplateDetailData; orgId?: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const target = orgId || user?.orgs?.[0]?.org_id;
  const reviewCopy = tpl.is_admin && !tpl.can_manage && tpl.status !== "approved";
  const [name, setName] = useState("");
  useEffect(() => setName(reviewCopy ? `Review — ${tpl.name}` : tpl.name.replace(/ template$/i, "")), [tpl.id, tpl.name, reviewCopy]);
  const use = useMutation({
    mutationFn: () =>
      api.post<{ id: string }>(`/api/orgs/${target}/projects/from-project-template`, {
        template_id: tpl.id,
        name: name.trim(),
      }),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["org", target, "projects"] });
      queryClient.invalidateQueries({ queryKey: ["template-gallery"] });
      router.push(`/org/${target}/projects/${project.id}`);
    },
    onError: (e: Error) => toast.error(e.message || "Could not start from the template"),
  });
  return (
    <div className="space-y-2 rounded-lg border p-3">
      <p className="flex items-center gap-1.5 text-sm font-medium">
        {reviewCopy ? <FlaskConical className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
        {reviewCopy ? "Open a test copy" : "Use this template"}
      </p>
      <p className="text-xs text-muted-foreground">
        {reviewCopy
          ? "Builds the exact app in your own organisation, to try before deciding. It is not counted as a use."
          : "Starts a new app from it. Smith asks whether you want the exact same app or one like it."}
      </p>
      <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name for your app" maxLength={255} />
      <Button className="w-full" onClick={() => use.mutate()} disabled={!target || !name.trim() || use.isPending}>
        {use.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {reviewCopy ? "Open test copy" : "Use template"}
      </Button>
      {!target && <p className="text-[11px] text-muted-foreground">Join or create an organisation first.</p>}
    </div>
  );
}

function ReviewState({
  tpl,
  onChanged,
  onSubmit,
}: {
  tpl: TemplateDetailData;
  onChanged: () => void;
  onSubmit?: (id: string) => void;
}) {
  const act = useMutation({
    mutationFn: (path: "cancel-request" | "unpublish") => api.post(`/api/project-templates/${tpl.id}/${path}`),
    onSuccess: (_d, path) => {
      onChanged();
      toast.success(path === "unpublish" ? "Taken out of the Gallery" : "Request taken back");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const failing = (tpl.checks ?? []).filter((c) => !c.ok);
  // Taking it out is for everyone at once, and coming back is a new review: asked first.
  const [confirmOut, setConfirmOut] = useState(false);
  useEffect(() => setConfirmOut(false), [tpl.id, tpl.status]);
  return (
    <div className="space-y-3 rounded-lg border p-3" data-testid="review-state">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">Review</p>
        <StatusBadge status={tpl.status} />
      </div>
      {tpl.review_note && (tpl.status === "rejected" || tpl.status === "removed" || tpl.status === "approved") && (
        <div className={cn("rounded-md p-2 text-xs", tpl.status === "approved" ? "bg-emerald-50 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200" : "bg-rose-50 text-rose-900 dark:bg-rose-950/40 dark:text-rose-200")}>
          <p className="font-medium">Tentoro said</p>
          <p className="mt-0.5 whitespace-pre-wrap">{tpl.review_note}</p>
        </div>
      )}
      {tpl.can_manage && (
        <div className="flex flex-col gap-2">
          {(tpl.status === "draft" || tpl.status === "rejected" || tpl.status === "removed") && onSubmit && (
            <Button size="sm" onClick={() => onSubmit(tpl.id)}>
              <Send className="mr-1.5 h-3.5 w-3.5" />
              {tpl.status === "draft" ? "Submit for review" : "Make changes and resubmit"}
            </Button>
          )}
          {tpl.status === "pending" && (
            <>
              <p className="text-xs text-muted-foreground">
                Waiting for Tentoro’s review. To change it, take the request back, change it, and send it again.
              </p>
              <Button size="sm" variant="ghost" onClick={() => act.mutate("cancel-request")} disabled={act.isPending}>
                Take back the request
              </Button>
            </>
          )}
          {tpl.status === "approved" && !confirmOut && (
            <Button size="sm" variant="ghost" onClick={() => setConfirmOut(true)} disabled={act.isPending}>
              Take out of the Gallery
            </Button>
          )}
          {tpl.status === "approved" && confirmOut && (
            <div className="space-y-2 rounded-md border border-rose-200 bg-rose-50/60 p-2 text-xs dark:border-rose-900 dark:bg-rose-950/30">
              <p>Nobody else can start an app from it after this; apps already made from it keep working.
                To put it back, submit it again and Tentoro reviews it again.</p>
              <div className="flex gap-2">
                <Button size="sm" variant="destructive" className="h-7 text-xs" onClick={() => act.mutate("unpublish")} disabled={act.isPending}>
                  Take it out
                </Button>
                <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setConfirmOut(false)}>Keep it</Button>
              </div>
            </div>
          )}
        </div>
      )}
      {failing.length > 0 && tpl.status !== "approved" && (
        <ul className="space-y-1 text-xs">
          {failing.map((c) => (
            <li key={c.key} className="flex gap-1.5">
              {c.blocking ? <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-600" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />}
              <span>{c.label}</span>
            </li>
          ))}
        </ul>
      )}
      {!!tpl.history?.length && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">History</p>
          <ol className="space-y-2 border-l pl-3">
            {tpl.history.map((h, i) => (
              <li key={i} className="relative text-xs">
                <span className="absolute -left-[17px] top-1 h-2 w-2 rounded-full bg-border" />
                <p className="font-medium">{STATUS_LABEL[h.status]}</p>
                <p className="text-muted-foreground">
                  {formatDate(h.at)}{h.by ? ` · ${h.by}` : ""}
                </p>
                {h.note && <p className="mt-0.5 whitespace-pre-wrap">{h.note}</p>}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function AdminPanel({ tpl, onChanged }: { tpl: TemplateDetailData; onChanged: () => void }) {
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: (decision: "approve" | "reject" | "remove") =>
      api.post(`/api/admin/template-requests/${tpl.id}/decision`, { decision, note: note.trim() }),
    onSuccess: (_d, decision) => {
      setNote("");
      onChanged();
      toast.success(
        decision === "approve" ? "Approved — it is in the Gallery, and the builder was told." :
        decision === "reject" ? "Sent back with your note; the builder was told." :
        "Taken out of the Gallery; the builder was told.",
      );
    },
    onError: (e: Error) => toast.error(e.message),
  });
  if (tpl.status !== "pending" && tpl.status !== "approved") return null;
  const blocking = (tpl.checks ?? []).filter((c) => c.blocking && !c.ok);
  return (
    <div className="space-y-2 rounded-lg border border-brand-900/30 bg-brand-900/[0.03] p-3" data-testid="admin-panel">
      <p className="flex items-center gap-1.5 text-sm font-medium">
        <ShieldCheck className="h-4 w-4" /> Tentoro review
      </p>
      {tpl.status === "pending" && (
        <ul className="space-y-1 text-xs">
          {(tpl.checks ?? []).map((c) => (
            <li key={c.key} className="flex gap-1.5">
              {c.ok ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" /> : c.blocking ? <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-600" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />}
              <span>{c.label}</span>
            </li>
          ))}
        </ul>
      )}
      <Textarea
        rows={3}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={2000}
        placeholder={tpl.status === "pending" ? "A note for the builder — required when asking for changes" : "Why it is being taken out (required)"}
      />
      {tpl.status === "pending" ? (
        <div className="flex gap-2">
          <Button size="sm" className="flex-1" onClick={() => decide.mutate("approve")} disabled={decide.isPending || blocking.length > 0}>
            <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" /> Approve
          </Button>
          <Button size="sm" variant="outline" className="flex-1" onClick={() => decide.mutate("reject")} disabled={decide.isPending || !note.trim()}>
            Request changes
          </Button>
        </div>
      ) : (
        <Button size="sm" variant="outline" className="w-full text-rose-700" onClick={() => decide.mutate("remove")} disabled={decide.isPending || !note.trim()}>
          <Trash2 className="mr-1.5 h-3.5 w-3.5" /> Take out of the Gallery
        </Button>
      )}
      {tpl.submitted_at && tpl.status === "pending" && (
        <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
          <Clock className="h-3 w-3" /> Waiting since {formatDate(tpl.submitted_at)}
        </p>
      )}
    </div>
  );
}

function Reviews({ tpl, onChanged }: { tpl: TemplateDetailData; onChanged: () => void }) {
  const queryClient = useQueryClient();
  const key = ["project-template", tpl.id, "reviews"];
  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => api.get<{ reviews: TemplateReviewData[] }>(`/api/project-templates/${tpl.id}/reviews`),
  });
  const [rating, setRating] = useState(tpl.my_review?.rating ?? 0);
  const [comment, setComment] = useState(tpl.my_review?.comment ?? "");
  useEffect(() => {
    setRating(tpl.my_review?.rating ?? 0);
    setComment(tpl.my_review?.comment ?? "");
  }, [tpl.id, tpl.my_review?.rating, tpl.my_review?.comment]);
  const done = () => {
    queryClient.invalidateQueries({ queryKey: key });
    onChanged();
  };
  const save = useMutation({
    mutationFn: () =>
      api.put(`/api/project-templates/${tpl.id}/reviews/mine`, { rating, comment: comment.trim() }),
    onSuccess: () => {
      done();
      toast.success("Thanks — your review is saved.");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/api/project-templates/${tpl.id}/reviews/mine`),
    onSuccess: () => {
      setRating(0);
      setComment("");
      done();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const [removing, setRemoving] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const moderate = useMutation({
    mutationFn: (id: string) => api.post(`/api/admin/template-reviews/${id}/remove`, { reason: reason.trim() }),
    onSuccess: () => {
      setRemoving(null);
      setReason("");
      done();
      toast.success("Review removed; its writer was told why.");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const reviews = data?.reviews ?? [];
  return (
    <div className="space-y-4">
      {tpl.can_rate && (
        <div className="space-y-2 rounded-lg border p-3" data-testid="my-review">
          <p className="text-sm font-medium">{tpl.my_review ? "Your review" : "Rate this template"}</p>
          <StarInput value={rating} onChange={setRating} />
          <Textarea
            rows={3}
            value={comment}
            maxLength={2000}
            onChange={(e) => setComment(e.target.value)}
            placeholder="What worked, what didn't, who it suits (optional)"
          />
          <div className="flex gap-2">
            <Button size="sm" onClick={() => save.mutate()} disabled={!rating || save.isPending}>
              {save.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              {tpl.my_review ? "Update review" : "Post review"}
            </Button>
            {tpl.my_review && (
              <Button size="sm" variant="ghost" onClick={() => remove.mutate()} disabled={remove.isPending}>
                Delete
              </Button>
            )}
          </div>
        </div>
      )}
      {tpl.status === "approved" && !tpl.can_rate && tpl.own_org && (
        <p className="text-xs text-muted-foreground">
          Your organisation built this template, so its rating is for others to give — but you can read what they say.
        </p>
      )}
      {tpl.status === "approved" && !tpl.can_rate && !tpl.own_org && !tpl.is_admin && (
        <p className="text-xs text-muted-foreground" data-testid="rate-after-use">
          Start an app from this template first (Use this template); then you can rate it here.
        </p>
      )}
      {isLoading ? (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      ) : reviews.length === 0 ? (
        <p className="text-sm text-muted-foreground">No reviews yet.</p>
      ) : (
        <ul className="space-y-3">
          {reviews.map((r) => (
            <li key={r.id} className="rounded-lg border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <PersonAvatar person={r.user} />
                <span className="text-sm font-medium">{r.user.name}</span>
                <Stars value={r.rating} />
                {r.used_it && (
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                    Used this template
                  </span>
                )}
                <span className="ml-auto text-[11px] text-muted-foreground">{formatDate(r.updated_at || r.created_at)}</span>
              </div>
              {r.comment && <p className="mt-2 whitespace-pre-wrap text-sm">{r.comment}</p>}
              {tpl.is_admin && removing !== r.id && (
                <button
                  type="button"
                  onClick={() => {
                    setRemoving(r.id);
                    setReason("");
                  }}
                  className="mt-2 inline-flex items-center gap-1 text-[11px] text-rose-700 hover:underline"
                >
                  <Trash2 className="h-3 w-3" /> Remove review
                </button>
              )}
              {tpl.is_admin && removing === r.id && (
                <div className="mt-2 space-y-2 rounded-md bg-rose-50 p-2 dark:bg-rose-950/40" data-testid="moderate">
                  <Textarea
                    rows={2}
                    value={reason}
                    maxLength={2000}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Why it is being removed — its writer is told (required)"
                  />
                  <div className="flex gap-2">
                    <Button size="sm" variant="destructive" onClick={() => moderate.mutate(r.id)} disabled={!reason.trim() || moderate.isPending}>
                      Remove
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setRemoving(null)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
