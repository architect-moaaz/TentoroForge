"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles, LayoutTemplate, Figma, Key, PenTool } from "lucide-react";
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

type Mode = "describe" | "template" | "design" | null;
/** Where an imported design comes from. Each provider is an adapter behind
 *  one backend contract (scope, tokens, markup, assets). */
type DesignProvider = "figma" | "uxpilot";

const FIGMA_URL_PATTERN = /figma\.com\/(file|design)\/[a-zA-Z0-9]+/;
const UXPILOT_REF_PATTERN = /^(https?:\/\/[^\s]+|[A-Za-z0-9_-]{4,})$/;

interface McpServerRow {
  id: string;
  name: string;
  server_url: string;
  enabled: boolean;
}

export function NewAppDialog({ orgId, open, onOpenChange }: NewAppDialogProps) {
  const [mode, setMode] = useState<Mode>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [provider, setProvider] = useState<DesignProvider>("figma");
  const [figmaUrl, setFigmaUrl] = useState("");
  const [figmaToken, setFigmaToken] = useState("");
  const [uxpilotRef, setUxpilotRef] = useState("");
  const [uxpilotServerId, setUxpilotServerId] = useState("");
  const [figmaServerId, setFigmaServerId] = useState("");
  const [figmaDescription, setFigmaDescription] = useState("");
  const [figmaUrlError, setFigmaUrlError] = useState<string | null>(null);
  const router = useRouter();
  const queryClient = useQueryClient();

  // The org's registered design MCP servers (Figma, UX Pilot), for the
  // connection picker. Listing is admin-gated; when it fails the backend
  // picks the org's only server for the provider itself, so a member
  // without the list can still import.
  const designServers = useQuery({
    queryKey: ["org", orgId, "mcp-servers", "design"],
    queryFn: async () => api.get<McpServerRow[]>(`/api/orgs/${orgId}/mcp-servers`),
    enabled: open && mode === "design",
    retry: false,
  });
  const serversFor = (p: DesignProvider) =>
    (designServers.data ?? []).filter(
      (r) => r.enabled && (p === "uxpilot" ? /uxpilot/i.test(r.server_url) : /figma\.com/i.test(r.server_url)),
    );
  const figmaServers = serversFor("figma");
  const uxpilotServerRows = serversFor("uxpilot");

  // Load saved Figma token from localStorage
  useEffect(() => {
    const saved = localStorage.getItem("figma_token");
    if (saved) setFigmaToken(saved);
  }, []);

  const createProject = useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      api.post<Project>(`/api/orgs/${orgId}/projects`, data),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "projects"] });
      onOpenChange(false);
      router.push(`/org/${orgId}/projects/${project.id}`);
    },
  });

  const providerLabel = provider === "uxpilot" ? "UX Pilot" : "Figma";
  const designRef = provider === "uxpilot" ? uxpilotRef.trim() : figmaUrl.trim();

  // Create project then trigger the design import via the chat SSE stream
  const createDesignProject = useMutation({
    mutationFn: async (data: { name: string; description: string }) => {
      const project = await api.post<Project>(`/api/orgs/${orgId}/projects`, {
        name: data.name,
        description: data.description,
      });
      if (provider === "figma" && figmaToken.trim()) {
        // A pasted token is kept in this browser only; the backend never stores it.
        localStorage.setItem("figma_token", figmaToken.trim());
      }
      return project;
    },
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "projects"] });
      onOpenChange(false);
      // Persist the trigger params for ChatPanel's auto-generation hook.
      // `description` here is the user's brief — ChatPanel forwards it to
      // /generate so the pipeline sees BOTH the design (for look and scope)
      // AND a plain-language app intent (for planner/business-logic context).
      const desc = figmaDescription.trim()
        ? figmaDescription.trim()
        : `Import from ${providerLabel}: ${designRef}`;
      const design =
        provider === "uxpilot"
          ? { provider, ref: designRef, credential_id: uxpilotServerId || undefined }
          : {
              provider,
              ref: designRef,
              credential_id: figmaServerId || undefined,
              token: figmaToken.trim() || undefined,
            };
      sessionStorage.setItem(
        `design_generate_${project.id}`,
        JSON.stringify({ design, description: desc }),
      );
      router.push(`/org/${orgId}/projects/${project.id}`);
    },
  });

  const handleCreate = () => {
    if (!name.trim()) return;
    createProject.mutate({ name: name.trim(), description: description.trim() || undefined });
  };

  // Figma no longer needs a pasted token: the org's Figma connection (or the
  // server's FIGMA_TOKEN) supplies it, and the backend says so if neither exists.
  const designReady =
    provider === "uxpilot"
      ? UXPILOT_REF_PATTERN.test(uxpilotRef.trim())
      : FIGMA_URL_PATTERN.test(figmaUrl);

  const handleDesignCreate = () => {
    if (!name.trim()) return;
    if (provider === "figma") {
      if (!FIGMA_URL_PATTERN.test(figmaUrl)) {
        setFigmaUrlError("Enter a valid Figma URL (e.g., https://www.figma.com/design/...)");
        return;
      }
    } else if (!UXPILOT_REF_PATTERN.test(uxpilotRef.trim())) {
      setFigmaUrlError("Enter a UX Pilot page id or the page's URL");
      return;
    }
    setFigmaUrlError(null);
    const desc = figmaDescription.trim()
      ? figmaDescription.trim()
      : `${providerLabel} import: ${designRef}`;
    createDesignProject.mutate({ name: name.trim(), description: desc });
  };

  const handleReset = () => {
    setMode(null);
    setName("");
    setDescription("");
    setProvider("figma");
    setFigmaUrl("");
    setUxpilotRef("");
    setUxpilotServerId("");
    setFigmaServerId("");
    setFigmaDescription("");
    setFigmaUrlError(null);
  };

  const isPending = createProject.isPending || createDesignProject.isPending;

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
              : mode === "design"
                ? "Import a design"
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
              onClick={() => setMode("design")}
              className="flex items-center gap-3 rounded-lg border p-4 text-left transition-colors hover:bg-accent"
            >
              <PenTool className="h-8 w-8 text-[#F24E1E]" />
              <div>
                <p className="font-medium">Import a design</p>
                <p className="text-sm text-muted-foreground">
                  Turn a Figma or UX Pilot design into a working app
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
        ) : mode === "design" ? (
          <div className="space-y-4 py-4">
            <div>
              <Label>Design source</Label>
              <div className="mt-1 grid grid-cols-2 gap-2" role="radiogroup" aria-label="Design source">
                <button
                  type="button"
                  role="radio"
                  aria-checked={provider === "figma"}
                  onClick={() => { setProvider("figma"); setFigmaUrlError(null); }}
                  className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors ${
                    provider === "figma" ? "border-foreground bg-accent" : "hover:bg-accent"
                  }`}
                >
                  <Figma className="h-4 w-4 text-[#F24E1E]" />
                  Figma
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={provider === "uxpilot"}
                  onClick={() => { setProvider("uxpilot"); setFigmaUrlError(null); }}
                  className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors ${
                    provider === "uxpilot" ? "border-foreground bg-accent" : "hover:bg-accent"
                  }`}
                >
                  <PenTool className="h-4 w-4 text-[#6C4CF1]" />
                  UX Pilot
                </button>
              </div>
            </div>
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
                1–3 sentences. {providerLabel} gives us the look; this tells us what the app does — used to pick the right integrations, entities, and workflows.
              </p>
            </div>
            {provider === "uxpilot" ? (
            <>
            <div>
              <Label htmlFor="uxpilot-ref" className="flex items-center gap-1.5">
                <PenTool className="h-3.5 w-3.5" />
                UX Pilot page
              </Label>
              <Input
                id="uxpilot-ref"
                value={uxpilotRef}
                onChange={(e) => {
                  setUxpilotRef(e.target.value);
                  setFigmaUrlError(null);
                }}
                placeholder="Page id, or paste the page's URL from UX Pilot"
                className="mt-1"
              />
              {figmaUrlError && (
                <p className="mt-1 text-xs text-destructive">{figmaUrlError}</p>
              )}
              <p className="mt-1 text-[11px] text-muted-foreground">
                Every design on the page becomes a screen. Reading a page spends no UX Pilot credits.
              </p>
            </div>
            <div>
              <Label htmlFor="uxpilot-server" className="flex items-center gap-1.5">
                <Key className="h-3.5 w-3.5" />
                UX Pilot connection
              </Label>
              {uxpilotServerRows.length > 0 ? (
                <select
                  id="uxpilot-server"
                  value={uxpilotServerId}
                  onChange={(e) => setUxpilotServerId(e.target.value)}
                  className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm"
                >
                  <option value="">Use the organization's UX Pilot server</option>
                  {uxpilotServerRows.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              ) : (
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Uses the UX Pilot MCP server registered under Settings → MCP Servers. The API key stays in that encrypted store.
                </p>
              )}
            </div>
            </>
            ) : (
            <>
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
            <div>
              <Label htmlFor="figma-server" className="flex items-center gap-1.5">
                <Key className="h-3.5 w-3.5" />
                Figma connection
              </Label>
              {figmaServers.length > 0 ? (
                <select
                  id="figma-server"
                  value={figmaServerId}
                  onChange={(e) => setFigmaServerId(e.target.value)}
                  className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm"
                >
                  <option value="">Use the organization's Figma connection</option>
                  {figmaServers.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              ) : (
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Uses the Figma server registered under Settings &rarr; MCP Servers (https://mcp.figma.com/mcp with a personal access token). The token stays in that encrypted store.
                </p>
              )}
            </div>
            <div>
              <Label htmlFor="figma-token" className="flex items-center gap-1.5">
                Personal access token (optional)
              </Label>
              <Input
                id="figma-token"
                type="password"
                value={figmaToken}
                onChange={(e) => setFigmaToken(e.target.value)}
                placeholder="figd_… only if no Figma connection is registered"
                className="mt-1"
              />
              <p className="mt-1 text-[11px] text-muted-foreground">
                Used for this import only and never stored on the server.
              </p>
            </div>
            </>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={handleReset}>
                Back
              </Button>
              <Button
                onClick={handleDesignCreate}
                disabled={!name.trim() || !designReady || isPending}
              >
                {createDesignProject.isPending ? "Creating..." : "Import & Generate"}
              </Button>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
