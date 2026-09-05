"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles, LayoutTemplate, Figma, Key } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Project } from "@/types/project";

interface NewAppDialogProps {
  orgId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Mode = "describe" | "template" | "figma" | null;

const FIGMA_URL_PATTERN = /figma\.com\/(file|design)\/[a-zA-Z0-9]+/;

export function NewAppDialog({ orgId, open, onOpenChange }: NewAppDialogProps) {
  const [mode, setMode] = useState<Mode>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [figmaUrl, setFigmaUrl] = useState("");
  const [figmaScope, setFigmaScope] =
    useState<"evidence" | "specification">("evidence");
  const [figmaDescription, setFigmaDescription] = useState("");
  const [figmaUrlError, setFigmaUrlError] = useState<string | null>(null);
  const router = useRouter();
  const queryClient = useQueryClient();

  // The load-saved-token effect went with the field that fed it: a PAT
  // in localStorage is a credential at rest in the browser (§42), and
  // nothing that runs ever read it back.

  const createProject = useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      api.post<Project>(`/api/orgs/${orgId}/projects`, data),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "projects"] });
      onOpenChange(false);
      router.push(`/org/${orgId}/projects/${project.id}`);
    },
  });

  // Create project then trigger Figma generation via the chat SSE stream
  const createFigmaProject = useMutation({
    mutationFn: async (data: {
      name: string;
      figmaUrl: string;
      figmaDescription: string;
    }) => {
      // Prefer the user's own words as the project description so the
      // planner/discovery/business-logic agents get real intent, not
      // "Figma import: <url>" boilerplate. Fall back to boilerplate only
      // if the user left it blank.
      const desc = data.figmaDescription.trim()
        ? data.figmaDescription.trim()
        : `Figma import: ${data.figmaUrl}`;
      const project = await api.post<Project>(`/api/orgs/${orgId}/projects`, {
        name: data.name,
        description: desc,
      });
      return project;
    },
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "projects"] });
      onOpenChange(false);
      // HANDED TO SMITH, NOT TO THE LEGACY PIPELINE.
      //
      // This wrote `figma_generate_<id>` for ChatPanel's auto-generation hook,
      // which posted to /api/projects/:id/generate. ChatPanel is mounted
      // NOWHERE — the project page swapped it for SmithPanel precisely because
      // /generate never reaches the Blueprint engine — so the trigger was
      // written and never read. The URL and the token were silently discarded
      // and nothing generated: an entry point that could not keep its promise.
      //
      // SmithPanel reads this key instead and connects the design through
      // `connect_figma`: the credential is resolved by NAME from the org's
      // integrations, `treatAs` is recorded, and the run that follows is the
      // ordinary Blueprint DAG.
      sessionStorage.setItem(
        `figma_connect_${project.id}`,
        JSON.stringify({
          figma_url: figmaUrl,
          treat_as: figmaScope,
          // The brief travels with it so the panel can START the definition
          // rather than leaving it typed in the composer for someone to press
          // send on. "Import design" should import the design.
          brief: figmaDescription.trim(),
        }),
      );
      router.push(`/org/${orgId}/projects/${project.id}`);
    },
  });

  const handleCreate = () => {
    if (!name.trim()) return;
    createProject.mutate({ name: name.trim(), description: description.trim() || undefined });
  };

  const handleFigmaCreate = () => {
    if (!name.trim()) return;
    if (!FIGMA_URL_PATTERN.test(figmaUrl)) {
      setFigmaUrlError("Enter a valid Figma URL (e.g., https://www.figma.com/design/...)");
      return;
    }
    setFigmaUrlError(null);
    createFigmaProject.mutate({
      name: name.trim(),
      figmaUrl,
      figmaDescription,
    });
  };

  const handleReset = () => {
    setMode(null);
    setName("");
    setDescription("");
    setFigmaUrl("");
    setFigmaDescription("");
    setFigmaUrlError(null);
  };

  const isPending = createProject.isPending || createFigmaProject.isPending;

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (!v) handleReset();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {mode === "describe"
              ? "Describe Your App"
              : mode === "figma"
                ? "Import from Figma"
                : mode === "template"
                  ? "Choose a Template"
                  : "Create New App"}
          </DialogTitle>
        </DialogHeader>

        {!mode ? (
          <div className="grid gap-3 py-4">
            <button
              onClick={() => setMode("describe")}
              className="flex items-center gap-3 rounded-lg border p-4 text-left transition-colors hover:bg-accent"
            >
              <Sparkles className="h-8 w-8 text-purple-500" />
              <div>
                <p className="font-medium">Describe Your App</p>
                <p className="text-sm text-muted-foreground">
                  Tell us what you need and AI will build it
                </p>
              </div>
            </button>
            <button
              onClick={() => setMode("figma")}
              className="flex items-center gap-3 rounded-lg border p-4 text-left transition-colors hover:bg-accent"
            >
              <Figma className="h-8 w-8 text-[#F24E1E]" />
              <div>
                <p className="font-medium">Import from Figma</p>
                <p className="text-sm text-muted-foreground">
                  Convert a Figma design into a working app
                </p>
              </div>
            </button>
            <button
              onClick={() => {
                onOpenChange(false);
                router.push(`/org/${orgId}/templates`);
              }}
              className="flex items-center gap-3 rounded-lg border p-4 text-left transition-colors hover:bg-accent"
            >
              <LayoutTemplate className="h-8 w-8 text-blue-500" />
              <div>
                <p className="font-medium">From Template</p>
                <p className="text-sm text-muted-foreground">
                  Start with a pre-built template and customize
                </p>
              </div>
            </button>
          </div>
        ) : mode === "describe" ? (
          <div className="space-y-4 py-4">
            <div>
              <Label htmlFor="app-name">App Name</Label>
              <Input
                id="app-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Inventory Manager"
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="app-desc">Description (optional)</Label>
              <textarea
                id="app-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g., Track inventory across warehouses with barcode scanning..."
                rows={3}
                className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={handleReset}>
                Back
              </Button>
              <Button onClick={handleCreate} disabled={!name.trim() || isPending}>
                {createProject.isPending ? "Creating..." : "Create App"}
              </Button>
            </div>
          </div>
        ) : mode === "figma" ? (
          <div className="space-y-4 py-4">
            <div>
              <Label htmlFor="figma-name">App Name</Label>
              <Input
                id="figma-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Marketing Dashboard"
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="figma-description">
                What is this app about?
              </Label>
              <Textarea
                id="figma-description"
                value={figmaDescription}
                onChange={(e) => setFigmaDescription(e.target.value)}
                placeholder="A visual product search app — users snap a photo and we compare prices across 40+ retailers."
                rows={3}
                className="mt-1"
              />
              <p className="mt-1 text-[11px] text-muted-foreground">
                1–3 sentences. Figma gives us the look; this tells us what the app does — used to pick the right integrations, entities, and workflows.
              </p>
            </div>
            <div>
              <Label htmlFor="figma-url" className="flex items-center gap-1.5">
                <Figma className="h-3.5 w-3.5" />
                Figma URL
              </Label>
              <Input
                id="figma-url"
                type="url"
                value={figmaUrl}
                onChange={(e) => {
                  setFigmaUrl(e.target.value);
                  setFigmaUrlError(null);
                }}
                placeholder="https://www.figma.com/design/abc123/My-Design"
                className="mt-1"
              />
              {figmaUrlError && (
                <p className="mt-1 text-xs text-destructive">{figmaUrlError}</p>
              )}
            </div>
            {/* NO TOKEN FIELD. It asked for the PAT and put it in
                localStorage — a credential at rest in the browser, which §42
                forbids — and then dropped it, because the only component that
                read it is mounted nowhere. The token now comes from the org's
                integrations, resolved by name at the moment of the call. */}
            <div>
              <Label className="flex items-center gap-1.5">
                <Key className="h-3.5 w-3.5" />
                Is this design the specification?
              </Label>
              <div className="mt-1.5 space-y-1.5">
                {([
                  ["evidence", "A reference", "The screens you drew are built from the design, and the rest of the app is built around them — usually more pages than frames."],
                  ["specification", "The specification", "One page per frame and nothing else — no sign-in, no lists, no forms unless you drew them."],
                ] as const).map(([value, label, help]) => (
                  <label
                    key={value}
                    className="flex cursor-pointer gap-2 rounded-md border p-2 text-xs"
                  >
                    <input
                      type="radio"
                      name="figma-scope"
                      checked={figmaScope === value}
                      onChange={() => setFigmaScope(value)}
                      className="mt-0.5"
                    />
                    <span>
                      <span className="font-medium">{label}</span>
                      <span className="block text-[11px] text-muted-foreground">
                        {help}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
              <p className="mt-1 text-[11px] text-muted-foreground">
                The Figma token comes from your organisation&apos;s integrations.
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={handleReset}>
                Back
              </Button>
              <Button
                onClick={handleFigmaCreate}
                disabled={!name.trim() || !figmaUrl || isPending}
              >
                {createFigmaProject.isPending ? "Creating..." : "Import design"}
              </Button>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
