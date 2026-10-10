"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LayoutTemplate, Loader2 } from "lucide-react";
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

/**
 * Save this project's application as a template for the organisation —
 * available at any point once Smith has defined something. The template is
 * a copy of the definition; the project itself is not changed.
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
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: () =>
      api.post<{ id: string; name: string }>(`/api/projects/${projectId}/templates`, {
        name: name.trim(),
        description: description.trim(),
      }),
    onSuccess: (tpl) => {
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ["project-templates", orgId] });
      toast.success(`Saved “${tpl.name}” to Templates`);
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
              same app again, or one like it. This app is not changed.
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
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              {save.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save template
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
