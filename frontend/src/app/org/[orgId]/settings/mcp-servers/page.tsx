"use client";

/**
 * /org/[orgId]/settings/mcp-servers — org-scoped registry of external MCP
 * (Model Context Protocol) servers. Once registered here, an MCP server
 * becomes pickable in the Agent Builder's Tool node ("MCP Server Tool" type)
 * and every agent in the org can call its tools.
 *
 * Wire-shape:
 *   GET    /api/orgs/{id}/mcp-servers                → McpServer[]
 *   POST   /api/orgs/{id}/mcp-servers                → McpServer
 *   PATCH  /api/orgs/{id}/mcp-servers/{sid}          → McpServer
 *   DELETE /api/orgs/{id}/mcp-servers/{sid}          → 204
 *   POST   /api/orgs/{id}/mcp-servers/{sid}/test     → { ok, tool_count?, error? }
 *
 * Secrets are write-only (returned as null on read) and encrypted at rest —
 * same contract as /api/orgs/{id}/integrations.
 */

import { use, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Server as ServerIcon,
  Plus,
  Pencil,
  Trash2,
  Check,
  X as XIcon,
  Loader2,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type McpTransport = "http" | "sse";
export type McpAuthKind = "none" | "bearer" | "apikey_header";

export interface McpServer {
  id: string;
  name: string;
  server_url: string;
  transport: McpTransport;
  auth_kind: McpAuthKind;
  auth_header_name?: string | null;
  enabled: boolean;
  updated_at?: string | null;
}

interface McpTestResult {
  ok: boolean;
  tool_count?: number;
  error?: string;
}

interface McpServerFormValues {
  name: string;
  server_url: string;
  transport: McpTransport;
  auth_kind: McpAuthKind;
  auth_secret: string;
  auth_header_name: string;
  enabled: boolean;
}

function emptyForm(): McpServerFormValues {
  return {
    name: "",
    server_url: "",
    transport: "http",
    auth_kind: "none",
    auth_secret: "",
    auth_header_name: "",
    enabled: true,
  };
}

function McpServersSettings({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const invalidateKey = ["mcpServers", orgId] as const;

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<McpServer | null>(null);
  // Per-row test state — { serverId: last-result } so multiple rows can show
  // their own status independently.
  const [testResults, setTestResults] = useState<
    Record<string, McpTestResult | "pending">
  >({});

  const { data: servers = [], isLoading } = useQuery<McpServer[]>({
    queryKey: invalidateKey,
    queryFn: () => api.get<McpServer[]>(`/api/orgs/${orgId}/mcp-servers`),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      api.delete(`/api/orgs/${orgId}/mcp-servers/${id}`),
    onSuccess: () => {
      toast.success("Server removed.");
      queryClient.invalidateQueries({ queryKey: invalidateKey });
    },
    onError: (err: any) =>
      toast.error(`Delete failed: ${err?.message ?? "unknown error"}`),
  });

  const runTest = async (server: McpServer) => {
    setTestResults((prev) => ({ ...prev, [server.id]: "pending" }));
    try {
      const result = await api.post<McpTestResult>(
        `/api/orgs/${orgId}/mcp-servers/${server.id}/test`,
      );
      setTestResults((prev) => ({ ...prev, [server.id]: result }));
      if (result.ok) {
        toast.success(
          `Connected — ${result.tool_count ?? 0} tool${
            result.tool_count === 1 ? "" : "s"
          } advertised.`,
        );
      } else {
        toast.error(`Test failed: ${result.error ?? "unknown error"}`);
      }
    } catch (err: any) {
      const errorResult: McpTestResult = {
        ok: false,
        error: err?.message ?? "unknown error",
      };
      setTestResults((prev) => ({ ...prev, [server.id]: errorResult }));
      toast.error(`Test failed: ${errorResult.error}`);
    }
  };

  const openAdd = () => {
    setEditing(null);
    setDialogOpen(true);
  };
  const openEdit = (server: McpServer) => {
    setEditing(server);
    setDialogOpen(true);
  };

  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold mb-2 flex items-center gap-2">
            <ServerIcon className="w-6 h-6" /> MCP Servers
          </h1>
          <p className="text-muted-foreground">
            MCP Servers — external tool servers that agents in this org can
            use. Register a server here once and it becomes pickable in every
            Agent Builder tool node as the &ldquo;MCP Server Tool&rdquo; type.
          </p>
        </div>
        <Button onClick={openAdd} data-testid="add-server-button">
          <Plus className="w-4 h-4 mr-1" />
          Add Server
        </Button>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : servers.length === 0 ? (
        <Card>
          <CardContent className="py-12 flex flex-col items-center gap-3 text-center">
            <ServerIcon className="w-10 h-10 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">No MCP servers registered</p>
              <p className="text-xs text-muted-foreground mt-1">
                Add one to start wiring MCP-backed tools into your agents.
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={openAdd}>
              <Plus className="w-3.5 h-3.5 mr-1" />
              Add your first server
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Registered servers</CardTitle>
            <CardDescription>
              {servers.length} server{servers.length === 1 ? "" : "s"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Name</th>
                    <th className="py-2 pr-3 font-medium">URL</th>
                    <th className="py-2 pr-3 font-medium">Transport</th>
                    <th className="py-2 pr-3 font-medium">Auth</th>
                    <th className="py-2 pr-3 font-medium">Enabled</th>
                    <th className="py-2 pr-3 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {servers.map((s) => {
                    const test = testResults[s.id];
                    return (
                      <tr
                        key={s.id}
                        className="border-b last:border-0 align-middle"
                        data-testid={`server-row-${s.id}`}
                      >
                        <td className="py-2 pr-3 font-medium">{s.name}</td>
                        <td className="py-2 pr-3 font-mono text-xs text-muted-foreground truncate max-w-[220px]">
                          {s.server_url}
                        </td>
                        <td className="py-2 pr-3">
                          <Badge variant="outline" className="text-[10px]">
                            {s.transport}
                          </Badge>
                        </td>
                        <td className="py-2 pr-3 text-xs">{s.auth_kind}</td>
                        <td className="py-2 pr-3">
                          {s.enabled ? (
                            <Badge variant="secondary" className="text-[10px] gap-1">
                              <Check className="w-3 h-3" /> On
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="text-[10px]">
                              Off
                            </Badge>
                          )}
                        </td>
                        <td className="py-2 pr-3">
                          <div className="flex items-center justify-end gap-1">
                            {test === "pending" ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />
                            ) : test?.ok ? (
                              <Badge
                                variant="secondary"
                                className="text-[10px] gap-1 bg-green-50 text-green-700 border-green-200"
                                data-testid={`test-ok-${s.id}`}
                              >
                                <Check className="w-3 h-3" />
                                {test.tool_count ?? 0} tool
                                {test.tool_count === 1 ? "" : "s"}
                              </Badge>
                            ) : test && !test.ok ? (
                              <Badge
                                variant="destructive"
                                className="text-[10px] gap-1"
                                data-testid={`test-err-${s.id}`}
                              >
                                <XIcon className="w-3 h-3" />
                                Failed
                              </Badge>
                            ) : null}
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => runTest(s)}
                              disabled={test === "pending"}
                              data-testid={`test-button-${s.id}`}
                            >
                              Test
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              onClick={() => openEdit(s)}
                              title="Edit"
                            >
                              <Pencil className="w-3.5 h-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              onClick={() => {
                                if (
                                  window.confirm(
                                    `Remove MCP server "${s.name}"? Agents still referencing it will fail at runtime.`,
                                  )
                                ) {
                                  deleteMutation.mutate(s.id);
                                }
                              }}
                              title="Delete"
                            >
                              <Trash2 className="w-3.5 h-3.5 text-muted-foreground" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {editing ? `Edit ${editing.name}` : "Add MCP Server"}
            </DialogTitle>
          </DialogHeader>
          <McpServerForm
            orgId={orgId}
            server={editing}
            onClose={() => setDialogOpen(false)}
            invalidateKey={invalidateKey}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}

function McpServerForm({
  orgId,
  server,
  onClose,
  invalidateKey,
}: {
  orgId: string;
  server: McpServer | null;
  onClose: () => void;
  invalidateKey: readonly unknown[];
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<McpServerFormValues>(
    server
      ? {
          name: server.name,
          server_url: server.server_url,
          transport: server.transport,
          auth_kind: server.auth_kind,
          auth_secret: "", // never populated — secrets are write-only
          auth_header_name: server.auth_header_name ?? "",
          enabled: server.enabled,
        }
      : emptyForm(),
  );

  const mutation = useMutation({
    mutationFn: async () => {
      // Trim empty fields so we don't POST empty strings for optional cols.
      // `auth_secret` also gets stripped when blank on an edit — that lets the
      // user update non-secret fields without re-typing the secret.
      const payload: Record<string, unknown> = {
        name: form.name,
        server_url: form.server_url,
        transport: form.transport,
        auth_kind: form.auth_kind,
        enabled: form.enabled,
      };
      if (form.auth_kind === "apikey_header" && form.auth_header_name) {
        payload.auth_header_name = form.auth_header_name;
      }
      if (form.auth_kind !== "none" && form.auth_secret) {
        payload.auth_secret = form.auth_secret;
      }
      if (server) {
        return api.put<McpServer>(
          `/api/orgs/${orgId}/mcp-servers/${server.id}`,
          payload,
        );
      }
      return api.post<McpServer>(`/api/orgs/${orgId}/mcp-servers`, payload);
    },
    onSuccess: () => {
      toast.success(server ? "Server updated." : "Server registered.");
      queryClient.invalidateQueries({ queryKey: invalidateKey });
      onClose();
    },
    onError: (err: any) =>
      toast.error(`Save failed: ${err?.message ?? "unknown error"}`),
  });

  const showSecret = form.auth_kind !== "none";
  const showHeaderName = form.auth_kind === "apikey_header";

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
    >
      <div className="space-y-4 py-2">
        <div className="space-y-1.5">
          <Label htmlFor="mcp-name">Name</Label>
          <Input
            id="mcp-name"
            required
            placeholder="e.g. Firecrawl"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="mcp-url">Server URL</Label>
          <Input
            id="mcp-url"
            required
            type="url"
            placeholder="https://mcp.example.com"
            value={form.server_url}
            onChange={(e) =>
              setForm({ ...form, server_url: e.target.value })
            }
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label>Transport</Label>
            <Select
              value={form.transport}
              onValueChange={(v) =>
                setForm({ ...form, transport: v as McpTransport })
              }
            >
              <SelectTrigger data-testid="transport-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="http">http</SelectItem>
                <SelectItem value="sse">sse</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Auth kind</Label>
            <Select
              value={form.auth_kind}
              onValueChange={(v) =>
                setForm({ ...form, auth_kind: v as McpAuthKind })
              }
            >
              <SelectTrigger data-testid="auth-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">none</SelectItem>
                <SelectItem value="bearer">bearer</SelectItem>
                <SelectItem value="apikey_header">apikey_header</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        {showHeaderName && (
          <div className="space-y-1.5">
            <Label htmlFor="mcp-header">Header name</Label>
            <Input
              id="mcp-header"
              placeholder="X-API-Key"
              value={form.auth_header_name}
              onChange={(e) =>
                setForm({ ...form, auth_header_name: e.target.value })
              }
            />
          </div>
        )}
        {showSecret && (
          <div className="space-y-1.5">
            <Label htmlFor="mcp-secret">
              Auth secret
              {server && (
                <span className="text-muted-foreground text-xs ml-1">
                  (leave blank to keep current)
                </span>
              )}
            </Label>
            <Input
              id="mcp-secret"
              type="password"
              autoComplete="new-password"
              placeholder={server ? "••••••••" : "Secret / token"}
              value={form.auth_secret}
              onChange={(e) =>
                setForm({ ...form, auth_secret: e.target.value })
              }
            />
          </div>
        )}
        <div className="flex items-center justify-between rounded border p-3">
          <div>
            <Label className="text-sm">Enabled</Label>
            <p className="text-xs text-muted-foreground">
              Disabled servers are hidden from the Agent Builder picker.
            </p>
          </div>
          <Switch
            checked={form.enabled}
            onCheckedChange={(v: boolean) => setForm({ ...form, enabled: v })}
            data-testid="enabled-switch"
          />
        </div>
      </div>
      <DialogFooter>
        <Button
          type="button"
          variant="outline"
          onClick={onClose}
          disabled={mutation.isPending}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : server ? "Save" : "Register"}
        </Button>
      </DialogFooter>
    </form>
  );
}

export default function McpServersSettingsPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <McpServersSettings orgId={orgId} />;
}
