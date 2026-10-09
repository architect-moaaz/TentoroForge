"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface OrgTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  created_by_name: string;
  created_at: string;
  can_manage: boolean;
  summary: {
    name: string;
    counts: Record<string, number>;
    pages: string[];
    palette: string[];
  };
}

const COUNTED: [string, string][] = [
  ["pages", "screens"],
  ["entities", "records"],
  ["workflows", "processes"],
  ["roles", "roles"],
];

/**
 * The templates this organisation saved from its own apps. Using one makes
 * a new project; Smith then asks whether it should be the exact same app or
 * one like it, and builds from the template either way.
 */
export function OrgTemplates({ orgId, search }: { orgId: string; search: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [using, setUsing] = useState<OrgTemplate | null>(null);
  const [deleting, setDeleting] = useState<OrgTemplate | null>(null);
  const [name, setName] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["project-templates", orgId],
    queryFn: () =>
      api.get<{ templates: OrgTemplate[] }>(`/api/orgs/${orgId}/project-templates`),
  });

  const use = useMutation({
    mutationFn: () =>
      api.post<{ id: string }>(`/api/orgs/${orgId}/projects/from-project-template`, {
        template_id: using!.id,
        name: name.trim(),
      }),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "projects"] });
      router.push(`/org/${orgId}/projects/${project.id}`);
    },
    onError: (err: Error) => toast.error(err.message || "Could not start from the template"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/api/project-templates/${id}`),
    onSuccess: () => {
      setDeleting(null);
      queryClient.invalidateQueries({ queryKey: ["project-templates", orgId] });
      toast.success("Template deleted");
    },
    onError: (err: Error) => toast.error(err.message || "Could not delete the template"),
  });

  const q = search.trim().toLowerCase();
  const templates = (data?.templates ?? []).filter(
    (t) => !q || `${t.name} ${t.description} ${t.category}`.toLowerCase().includes(q),
  );

  return (
    <section className="mb-10">
      <div className="mb-3">
        <h2 className="text-base font-semibold text-foreground">Your templates</h2>
        <p className="text-xs text-muted-foreground">
          Saved from your organisation&apos;s apps. Use “Save as template” at the top of any
          project, or ask Smith.
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
          {templates.map((t) => {
            const counts = COUNTED.filter(([k]) => t.summary?.counts?.[k]).map(
              ([k, label]) => `${t.summary.counts[k]} ${label}`,
            );
            return (
              <div key={t.id} className="flex flex-col rounded-lg border bg-card p-4">
                {!!t.summary?.palette?.length && (
                  <div className="mb-3 flex gap-1">
                    {t.summary.palette.map((c) => (
                      <span
                        key={c}
                        className="h-3 w-6 rounded-sm border"
                        style={{ backgroundColor: c }}
                      />
                    ))}
                  </div>
                )}
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-sm font-medium text-foreground">{t.name}</h3>
                  {t.can_manage && (
                    <button
                      onClick={() => setDeleting(t)}
                      aria-label={`Delete ${t.name}`}
                      className="text-muted-foreground hover:text-destructive"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                {t.description && (
                  <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">
                    {t.description}
                  </p>
                )}
                {counts.length > 0 && (
                  <p className="mt-2 text-xs text-foreground/80">{counts.join(" · ")}</p>
                )}
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {t.created_by_name ? `by ${t.created_by_name} · ` : ""}
                  {new Date(t.created_at).toLocaleDateString()}
                </p>
                <Button
                  size="sm"
                  className="mt-3"
                  onClick={() => {
                    setName(t.summary?.name || t.name.replace(/ template$/i, ""));
                    setUsing(t);
                  }}
                >
                  Use template
                </Button>
              </div>
            );
          })}
        </div>
      )}

      <Dialog open={!!using} onOpenChange={(o) => !o && setUsing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Start from “{using?.name}”</DialogTitle>
            <DialogDescription>
              A new project is made from this template. Smith will ask whether you want the
              exact same app or something like it but different.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="New project name"
            maxLength={255}
            autoFocus
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setUsing(null)}>
              Cancel
            </Button>
            <Button onClick={() => use.mutate()} disabled={!name.trim() || use.isPending}>
              {use.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Create project
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete “{deleting?.name}”?</DialogTitle>
            <DialogDescription>
              It disappears from Templates for everyone in the organisation. Apps already made
              from it keep working — each has its own copy.
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
