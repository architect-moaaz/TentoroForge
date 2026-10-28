"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ImagePlus,
  Loader2,
  MonitorSmartphone,
  Send,
  Star,
  X,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { TemplateCheck, TemplateDetailData, TemplateShot } from "@/lib/templateGallery";
import { Shot, StatusBadge } from "./TemplateBits";

const STEPS = ["Details", "Screenshots", "Checks"] as const;
const DESCRIPTION_MIN = 30;
const SHOT_MAX = 8;
const ACCEPT = "image/png,image/jpeg,image/webp";

/**
 * Send a template to Tentoro for the Gallery: say what it is, show it, and
 * see it pass the checks a reviewer needs — then submit. Everything is saved
 * as it is changed, so closing half-way loses nothing; the template stays a
 * private one of the organisation until it is approved.
 */
export function SubmitTemplateDialog({
  templateId,
  orgId,
  open,
  onOpenChange,
  startAt = 0,
}: {
  templateId: string | null;
  orgId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  startAt?: number;
}) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState(startAt);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [uploading, setUploading] = useState(0);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const loadedFor = useRef<string | null>(null);

  const detailKey = ["project-template", templateId, "detail"];
  const { data: tpl, isLoading } = useQuery({
    queryKey: detailKey,
    queryFn: () => api.get<TemplateDetailData>(`/api/project-templates/${templateId}/detail`),
    enabled: open && !!templateId,
  });
  const checksQuery = useQuery({
    queryKey: ["project-template", templateId, "checks"],
    queryFn: () =>
      api.get<{ checks: TemplateCheck[]; ready: boolean }>(`/api/project-templates/${templateId}/checks`),
    enabled: open && !!templateId && step === 2,
  });

  useEffect(() => {
    if (open) setStep(startAt);
    if (!open) loadedFor.current = null;
  }, [open, startAt]);
  useEffect(() => {
    if (tpl && loadedFor.current !== tpl.id) {
      loadedFor.current = tpl.id;
      setName(tpl.name);
      setDescription(tpl.description);
      setCategory(tpl.category);
    }
  }, [tpl]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["project-template", templateId] });
    queryClient.invalidateQueries({ queryKey: ["project-templates", orgId] });
  };

  const saveDetails = useMutation({
    mutationFn: () =>
      api.patch(`/api/project-templates/${templateId}`, {
        name: name.trim(),
        description: description.trim(),
        category: category.trim(),
      }),
    onSuccess: () => {
      refresh();
      setStep(1);
    },
    onError: (e: Error) => toast.error(e.message || "Could not save the details"),
  });

  const addFromApp = useMutation({
    mutationFn: () =>
      api.post<{ added: TemplateShot[]; available: number }>(
        `/api/project-templates/${templateId}/screenshots/from-app`,
      ),
    onSuccess: (r) => {
      refresh();
      if (r.added.length) toast.success(`Added ${r.added.length} screen${r.added.length === 1 ? "" : "s"} from the app`);
      else if (!r.available) toast.message("The app has no pictures of its screens yet — build it, or upload your own.");
      else toast.message("The app's screens are already added, or there is no room for more.");
    },
    onError: (e: Error) => toast.error(e.message || "Could not add the app's screens"),
  });

  const removeShot = useMutation({
    mutationFn: (id: string) => api.delete(`/api/project-templates/${templateId}/screenshots/${id}`),
    onSuccess: refresh,
    onError: (e: Error) => toast.error(e.message || "Could not remove it"),
  });

  const caption = useMutation({
    mutationFn: ({ id, caption }: { id: string; caption: string }) =>
      api.patch(`/api/project-templates/${templateId}/screenshots/${id}`, { caption }),
    onSuccess: refresh,
    onError: (e: Error) => toast.error(e.message || "Could not save the caption"),
  });

  const reorder = useMutation({
    mutationFn: (order: string[]) =>
      api.put(`/api/project-templates/${templateId}/screenshots/order`, { order }),
    onSuccess: refresh,
  });

  const submit = useMutation({
    mutationFn: () =>
      api.post(`/api/project-templates/${templateId}/submit`, { pricing_model: "free" }),
    onSuccess: () => {
      refresh();
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      toast.success("Sent to Tentoro for review — you'll be told when it is decided.");
      onOpenChange(false);
    },
    onError: (e: Error) => {
      checksQuery.refetch();
      toast.error(e.message || "Could not submit it");
    },
  });

  async function upload(files: FileList | File[]) {
    const list = Array.from(files);
    const room = SHOT_MAX - (tpl?.screenshots.length ?? 0);
    if (room <= 0) {
      toast.message(`All ${SHOT_MAX} places are taken — remove a picture to add another.`);
      return;
    }
    if (list.length > room) {
      toast.message(room === 1 ? "Only 1 more fits — the first picture is added."
                                : `Only ${room} more fit — the first ${room} are added.`);
    }
    for (const file of list.slice(0, Math.max(0, room))) {
      setUploading((n) => n + 1);
      try {
        const form = new FormData();
        form.append("file", file);
        await api.upload(`/api/project-templates/${templateId}/screenshots`, form);
      } catch (e) {
        toast.error(`${file.name}: ${(e as Error).message || "could not be added"}`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
    refresh();
  }

  function move(index: number, by: number) {
    const ids = (tpl?.screenshots ?? []).map((s) => s.id);
    const to = index + by;
    if (to < 0 || to >= ids.length) return;
    [ids[index], ids[to]] = [ids[to], ids[index]];
    reorder.mutate(ids);
  }

  const shots = tpl?.screenshots ?? [];
  const descShort = description.trim().length < DESCRIPTION_MIN;
  const locked = tpl && !tpl.editable;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Submit to the Templates Gallery
            {tpl && <StatusBadge status={tpl.status} />}
          </DialogTitle>
          <DialogDescription>
            Tentoro reviews every template before it is shared with everyone. Until then it stays
            private to your organisation, which can already use it.
          </DialogDescription>
        </DialogHeader>

        <ol className="flex items-center gap-2 text-xs" aria-label="Steps">
          {STEPS.map((label, i) => (
            <li key={label} className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => !locked && i <= Math.max(step, 1) && setStep(i)}
                className={cn(
                  "flex items-center gap-1.5 rounded-full px-2.5 py-1 font-medium",
                  i === step ? "bg-brand-900 text-white" : "bg-muted text-muted-foreground",
                )}
                aria-current={i === step ? "step" : undefined}
              >
                <span className="tabular-nums">{i + 1}</span> {label}
              </button>
              {i < STEPS.length - 1 && <span className="h-px w-6 bg-border" />}
            </li>
          ))}
        </ol>

        {isLoading || !tpl ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : locked ? (
          <p className="rounded-lg border bg-muted/40 p-4 text-sm text-muted-foreground">
            {tpl.status === "pending"
              ? "This version is waiting for Tentoro's review, so it can't be changed now. To change it, open it and press “Take back the request”, make your changes, then send it again."
              : tpl.status === "approved"
              ? "This version is in the Gallery as it was approved. To change it, save the app as a template again — that makes the next version, which is reviewed in turn."
              : "A newer version of this template is in the Gallery; this one can no longer be submitted."}
          </p>
        ) : step === 0 ? (
          <div className="space-y-4">
            {tpl.status === "rejected" && tpl.review_note && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
                <p className="font-medium">Tentoro asked for changes</p>
                <p className="mt-1 whitespace-pre-wrap">{tpl.review_note}</p>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="tpl-name">Name</Label>
              <Input id="tpl-name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tpl-desc">What it is for</Label>
              <Textarea
                id="tpl-desc"
                rows={4}
                maxLength={2000}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What the app does, who it is for, and what a team gets by starting from it."
              />
              <p className={cn("text-[11px]", descShort ? "text-amber-700 dark:text-amber-400" : "text-muted-foreground")}>
                {descShort
                  ? `At least ${DESCRIPTION_MIN} characters — ${DESCRIPTION_MIN - description.trim().length} to go.`
                  : `${description.trim().length} characters`}
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tpl-cat">Category</Label>
              <Input
                id="tpl-cat"
                value={category}
                maxLength={60}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="e.g. HR, Finance, Operations"
              />
            </div>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Price</legend>
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-brand-900 bg-brand-900/5 p-3">
                  <input type="radio" name="pricing" checked readOnly className="mt-1" />
                  <span>
                    <span className="block text-sm font-medium">Free</span>
                    <span className="block text-xs text-muted-foreground">Anyone can start an app from it.</span>
                  </span>
                </label>
                <label
                  className="flex items-start gap-2 rounded-lg border p-3 opacity-60"
                  title="Paid templates are coming soon"
                >
                  <input type="radio" name="pricing" disabled className="mt-1" />
                  <span>
                    <span className="flex items-center gap-1.5 text-sm font-medium">
                      Paid <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium">Coming soon</span>
                    </span>
                    <span className="block text-xs text-muted-foreground">Set a price people pay to use it.</span>
                    <span className="mt-2 flex gap-2" aria-hidden>
                      <input disabled placeholder="Amount" className="h-7 w-24 rounded border bg-muted px-2 text-xs" />
                      <select disabled className="h-7 rounded border bg-muted px-1 text-xs">
                        <option>USD</option>
                      </select>
                    </span>
                  </span>
                </label>
              </div>
            </fieldset>
          </div>
        ) : step === 1 ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Show the app the way a team would see it. The first picture is the cover in the Gallery.
              PNG, JPEG or WebP, up to 5 MB each, {SHOT_MAX} at most.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => addFromApp.mutate()}
                disabled={addFromApp.isPending || shots.length >= SHOT_MAX || !tpl.source_project_id}
              >
                {addFromApp.isPending ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <MonitorSmartphone className="mr-1.5 h-3.5 w-3.5" />
                )}
                Add the app&apos;s own screens
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => fileInput.current?.click()}
                disabled={shots.length >= SHOT_MAX}
              >
                <ImagePlus className="mr-1.5 h-3.5 w-3.5" /> Upload pictures
              </Button>
              <input
                ref={fileInput}
                type="file"
                accept={ACCEPT}
                multiple
                hidden
                onChange={(e) => {
                  if (e.target.files?.length) upload(e.target.files);
                  e.target.value = "";
                }}
              />
            </div>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                if (e.dataTransfer.files?.length) upload(e.dataTransfer.files);
              }}
              className={cn(
                "rounded-lg border-2 border-dashed p-3 transition-colors",
                dragging ? "border-brand-900 bg-brand-900/5" : "border-border",
              )}
            >
              {shots.length === 0 && uploading === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  Drop pictures here, or use the buttons above.
                </p>
              ) : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  {shots.map((s, i) => (
                    <figure key={s.id} className="group relative overflow-hidden rounded-md border bg-card">
                      <Shot templateId={tpl.id} shotId={s.id} alt={s.caption || `Screenshot ${i + 1}`} className="aspect-[16/10] w-full" />
                      {i === 0 && (
                        <span className="absolute left-1.5 top-1.5 inline-flex items-center gap-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
                          <Star className="h-2.5 w-2.5" /> Cover
                        </span>
                      )}
                      <div className="absolute right-1.5 top-1.5 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                        <button type="button" aria-label="Move earlier" disabled={i === 0} onClick={() => move(i, -1)} className="rounded bg-black/70 p-1 text-white disabled:opacity-40">
                          <ArrowUp className="h-3 w-3" />
                        </button>
                        <button type="button" aria-label="Move later" disabled={i === shots.length - 1} onClick={() => move(i, 1)} className="rounded bg-black/70 p-1 text-white disabled:opacity-40">
                          <ArrowDown className="h-3 w-3" />
                        </button>
                        <button type="button" aria-label="Remove screenshot" onClick={() => removeShot.mutate(s.id)} className="rounded bg-black/70 p-1 text-white">
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                      <figcaption className="border-t">
                        <input
                          key={`${s.id}:${s.caption}`}
                          defaultValue={s.caption}
                          maxLength={200}
                          placeholder="Say what this shows"
                          aria-label={`Caption for screenshot ${i + 1}`}
                          onBlur={(e) => {
                            const next = e.target.value.trim();
                            if (next !== s.caption) caption.mutate({ id: s.id, caption: next });
                          }}
                          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                          className="w-full bg-transparent px-2 py-1 text-[11px] text-muted-foreground outline-none focus:text-foreground"
                        />
                      </figcaption>
                    </figure>
                  ))}
                  {Array.from({ length: uploading }).map((_, i) => (
                    <div key={`up-${i}`} className="flex aspect-[16/10] items-center justify-center rounded-md border bg-muted">
                      <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                    </div>
                  ))}
                </div>
              )}
            </div>
            <p className="text-right text-[11px] text-muted-foreground">
              {shots.length} of {SHOT_MAX}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              These are checked again by Tentoro before it is approved.
            </p>
            {checksQuery.isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            ) : (
              <ul className="space-y-2">
                {(checksQuery.data?.checks ?? []).map((c) => (
                  <li key={c.key} className="flex items-start gap-2 text-sm" data-check={c.key} data-ok={c.ok}>
                    {c.ok ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                    ) : c.blocking ? (
                      <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
                    ) : (
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                    )}
                    <span>
                      <span className={cn(!c.ok && c.blocking && "font-medium")}>{c.label}</span>
                      {c.detail && <span className="block text-xs text-muted-foreground">{c.detail}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <div className="rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
              <p>
                <span className="font-medium text-foreground">{name || tpl.name}</span> · version {tpl.version} · Free
              </p>
              <p className="mt-1">
                Submitting tells Tentoro&apos;s team. You&apos;ll see its status in Templates and be
                notified when it is approved or if changes are needed.
              </p>
            </div>
          </div>
        )}

        {!locked && tpl && (
          <DialogFooter className="gap-2 sm:justify-between">
            <Button variant="ghost" onClick={() => (step === 0 ? onOpenChange(false) : setStep(step - 1))}>
              {step === 0 ? "Cancel" : "Back"}
            </Button>
            {step === 0 ? (
              <Button onClick={() => saveDetails.mutate()} disabled={saveDetails.isPending || name.trim().length < 3}>
                {saveDetails.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Next: screenshots
              </Button>
            ) : step === 1 ? (
              <Button onClick={() => setStep(2)} disabled={uploading > 0}>
                Next: checks
              </Button>
            ) : (
              <Button
                onClick={() => submit.mutate()}
                // Fresh checks only: coming back after removing pictures must not
                // submit on what the last visit found (nor on a double-click of Next).
                disabled={submit.isPending || checksQuery.isFetching || !checksQuery.data?.ready || tpl.status === "pending"}
              >
                {submit.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                {tpl.status === "pending" ? "Waiting for review" : "Submit for review"}
              </Button>
            )}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
