"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Send, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatDate, type TemplateCardData } from "@/lib/templateGallery";
import { GalleryCard } from "./GalleryCard";

/** What the builder sees under each of their templates: where it stands, and the next step. */
function StatusLine({ t }: { t: TemplateCardData }) {
  switch (t.status) {
    case "draft":
      return <>Private to your organisation. Submit it to share it in the Gallery.</>;
    case "pending":
      return <>Sent to Tentoro {t.submitted_at ? formatDate(t.submitted_at) : ""} — waiting for review.</>;
    case "approved":
      return <>In the Gallery since {formatDate(t.published_at)}.</>;
    case "rejected":
      return (
        <>
          <span className="font-medium">Tentoro asked for changes:</span> {t.review_note}
        </>
      );
    case "removed":
      return <>Taken out of the Gallery{t.review_note ? `: ${t.review_note}` : "."}</>;
    case "superseded":
      return <>A newer version is in the Gallery.</>;
  }
}

/**
 * The templates this organisation saved from its own apps, and where each
 * stands with Tentoro. A template is usable here at once, whatever its
 * status; submitted and approved, it is in the Gallery for everyone.
 */
export function OrgTemplates({
  orgId,
  search,
  onOpen,
  onSubmit,
}: {
  orgId: string;
  search: string;
  onOpen: (templateId: string) => void;
  onSubmit: (templateId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [deleting, setDeleting] = useState<TemplateCardData | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["project-templates", orgId],
    queryFn: () => api.get<{ templates: TemplateCardData[] }>(`/api/orgs/${orgId}/project-templates`),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/api/project-templates/${id}`),
    onSuccess: () => {
      setDeleting(null);
      queryClient.invalidateQueries({ queryKey: ["project-templates", orgId] });
      queryClient.invalidateQueries({ queryKey: ["template-gallery"] });
      toast.success("Template deleted");
    },
    onError: (err: Error) => toast.error(err.message || "Could not delete the template"),
  });

  const q = search.trim().toLowerCase();
  const templates = (data?.templates ?? []).filter(
    (t) => !q || `${t.name} ${t.description} ${t.category}`.toLowerCase().includes(q),
  );
  const waiting = templates.filter((t) => t.status === "pending").length;

  return (
    <section className="mb-10" aria-labelledby="org-templates-heading">
      <div className="mb-3">
        <h2 id="org-templates-heading" className="text-base font-semibold text-foreground">
          Your templates
          {waiting > 0 && (
            <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300">
              {waiting} in review
            </span>
          )}
        </h2>
        <p className="text-xs text-muted-foreground">
          Saved from your organisation&apos;s apps with “Save as template” at the top of any project, or
          by asking Smith. Anyone here can use them; submit one to share it in the Gallery.
        </p>
      </div>

      {isLoading ? (
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      ) : templates.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
          {q ? "No saved templates match." : "No saved templates yet."}
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {templates.map((t) => (
            <div key={t.id} className="flex flex-col gap-2" data-org-template={t.id} data-status={t.status}>
              <GalleryCard tpl={t} onOpen={() => onOpen(t.id)} showStatus />
              <p className="px-1 text-[11px] leading-snug text-muted-foreground">
                <StatusLine t={t} />
              </p>
              {t.can_manage && (
                <div className="flex items-center gap-2 px-1">
                  {(t.status === "draft" || t.status === "rejected" || t.status === "removed") && (
                    <Button size="sm" className="h-7 text-xs" onClick={() => onSubmit(t.id)}>
                      <Send className="mr-1 h-3 w-3" />
                      {t.status === "draft" ? "Submit for review" : "Resubmit"}
                    </Button>
                  )}
                  {t.status === "pending" && (
                    <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onOpen(t.id)}>
                      View request
                    </Button>
                  )}
                  <button
                    onClick={() => setDeleting(t)}
                    aria-label={`Delete ${t.name}`}
                    className="ml-auto text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <Dialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete “{deleting?.name}”?</DialogTitle>
            <DialogDescription>
              It disappears from Templates for everyone in the organisation
              {deleting?.status === "approved" ? " and from the Gallery" : ""}
              {deleting?.status === "pending" ? ", and its review request is withdrawn" : ""}. Apps
              already made from it keep working — each has its own copy.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleting && remove.mutate(deleting.id)}
              disabled={remove.isPending}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
