"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LayoutTemplate, Loader2, Send } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SubmitTemplateDialog } from "./SubmitTemplateDialog";

/**
 * Save this project's application as a template for the organisation —
 * available at any point once Smith has defined something. The template is
 * a copy of the definition; the project itself is not changed.
 *
 * Saved, it is private to the organisation. "Save and publish" goes straight
 * on to the Gallery request: screenshots, the checks, and Submit — Tentoro
 * reviews it before anyone else can see it.
 */
export function SaveAsTemplateButton({
  projectId,
  orgId,
  projectName,
}: {
  projectId: string;
  orgId: string;
  projectName?: string;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [publishing, setPublishing] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: (_publish: boolean) =>
      api.post<{ id: string; name: string; version: number }>(`/api/projects/${projectId}/templates`, {
        name: name.trim(),
        description: description.trim(),
      }),
    onSuccess: (tpl, publish) => {
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ["project-templates", orgId] });
      const v = tpl.version > 1 ? ` (version ${tpl.version})` : "";
      if (publish) {
        setPublishing(tpl.id);
      } else {
        toast.success(`Saved “${tpl.name}”${v} to Templates — private to your organisation`);
      }
    },
    onError: (err: Error) => toast.error(err.message || "Could not save the template"),
  });

  return (
    <>
      <button
        onClick={() => {
          setName(projectName ? `${projectName} template` : "");
          setDescription("");
          setOpen(true);
        }}
        aria-label="Save as template"
        title="Save as template"
        className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors dark:hover:bg-slate-800"
      >
        <LayoutTemplate className="h-3.5 w-3.5" />
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save as template</DialogTitle>
            <DialogDescription>
              Anyone in your organisation can start a new app from it in Templates — the exact
              same app again, or one like it. To share it with every team on Tentoro Forge,
              publish it to the Gallery: Tentoro reviews it first. This app is not changed.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Template name"
              maxLength={120}
              autoFocus
            />
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What it is for (optional — the app's own description is used otherwise)"
              maxLength={2000}
              rows={3}
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="outline" onClick={() => save.mutate(false)} disabled={save.isPending}>
              {save.isPending && !save.variables && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save, keep private
            </Button>
            <Button onClick={() => save.mutate(true)} disabled={save.isPending}>
              {save.isPending && save.variables ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-2 h-4 w-4" />
              )}
              Save and publish…
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <SubmitTemplateDialog
        templateId={publishing}
        orgId={orgId}
        open={!!publishing}
        startAt={1}
        onOpenChange={(o) => !o && setPublishing(null)}
      />
    </>
  );
}
