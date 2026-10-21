"use client";

/**
 * /org/[orgId]/settings/mcp-servers — the organisation's registry of MCP
 * (Model Context Protocol) servers: the tool servers every agent in the
 * organisation may call. Registered once here, a server is pickable in the
 * Agent Builder's Tool node as the "MCP Server Tool" type.
 *
 * One card per server, saying what it is, how it is reached and whether it
 * answered the last time it was tried; the form explains each choice in
 * plain words instead of showing the wire values alone.
 *
 * Wire-shape:
 *   GET    /api/orgs/{id}/mcp-servers                → McpServer[]
 *   POST   /api/orgs/{id}/mcp-servers                → McpServer
 *   PUT    /api/orgs/{id}/mcp-servers/{sid}          → McpServer
 *   DELETE /api/orgs/{id}/mcp-servers/{sid}          → 204
 *   POST   /api/orgs/{id}/mcp-servers/{sid}/test     → { ok, tool_count?, error? }
 *
 * Secrets are write-only (returned as null on read) and encrypted at rest —
 * the same contract as /api/orgs/{id}/integrations.
 */

import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Eye, EyeOff, KeyRound, Loader2, Pencil, Plug, Plus, Server as ServerIcon, Trash2, X as XIcon } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

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

interface McpTestResult { ok: boolean; tool_count?: number; error?: string }

/** The wire values, said in words where they are chosen and where they are shown. */
export const TRANSPORTS: ReadonlyArray<{ value: McpTransport; title: string; hint: string }> = [
  { value: "http", title: "Streamable HTTP", hint: "The current MCP transport: one endpoint, requests and streamed replies." },
  { value: "sse", title: "Server-sent events", hint: "The older transport: an event stream plus a message endpoint." },
];
export const AUTH_KINDS: ReadonlyArray<{ value: McpAuthKind; title: string; hint: string }> = [
  { value: "none", title: "No authentication", hint: "The server is open, or guarded by the network." },
  { value: "bearer", title: "Bearer token", hint: "Sent as `Authorization: Bearer <token>` on every call." },
  { value: "apikey_header", title: "API key header", hint: "Sent in a header you name, such as X-API-Key." },
];
const title = (list: ReadonlyArray<{ value: string; title: string }>, value: string) => list.find((x) => x.value === value)?.title ?? value;

/** The host of a server address, for the card; the whole address when it will not parse. */
export function hostOf(url: string): string {
  try { return new URL(url).host; } catch { return url; }
}

interface McpServerFormValues {
  name: string; server_url: string; transport: McpTransport; auth_kind: McpAuthKind;
  auth_secret: string; auth_header_name: string; enabled: boolean;
}
const emptyForm = (): McpServerFormValues =>
  ({ name: "", server_url: "", transport: "http", auth_kind: "none", auth_secret: "", auth_header_name: "", enabled: true });

function McpServersSettings({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const invalidateKey = ["mcpServers", orgId] as const;
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<McpServer | null>(null);
  // Per-server test state, so several cards can show their own result.
  const [testResults, setTestResults] = useState<Record<string, McpTestResult | "pending">>({});

  const { data: servers = [], isLoading } = useQuery<McpServer[]>({
    queryKey: invalidateKey,
    queryFn: () => api.get<McpServer[]>(`/api/orgs/${orgId}/mcp-servers`),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/api/orgs/${orgId}/mcp-servers/${id}`),
    onSuccess: () => { toast.success("Server removed."); queryClient.invalidateQueries({ queryKey: invalidateKey }); },
    onError: (err: unknown) => toast.error(`Delete failed: ${err instanceof Error ? err.message : "unknown error"}`),
  });

  const runTest = async (server: McpServer) => {
    setTestResults((prev) => ({ ...prev, [server.id]: "pending" }));
    try {
      const result = await api.post<McpTestResult>(`/api/orgs/${orgId}/mcp-servers/${server.id}/test`);
      setTestResults((prev) => ({ ...prev, [server.id]: result }));
      if (result.ok) toast.success(`Connected — ${result.tool_count ?? 0} tool${result.tool_count === 1 ? "" : "s"} advertised.`);
      else toast.error(`Test failed: ${result.error ?? "unknown error"}`);
    } catch (err: unknown) {
      const errorResult: McpTestResult = { ok: false, error: err instanceof Error ? err.message : "unknown error" };
      setTestResults((prev) => ({ ...prev, [server.id]: errorResult }));
      toast.error(`Test failed: ${errorResult.error}`);
    }
  };

  const openAdd = () => { setEditing(null); setDialogOpen(true); };
  const openEdit = (server: McpServer) => { setEditing(server); setDialogOpen(true); };
  const on = servers.filter((s) => s.enabled).length;

  return (
    <div className="p-8">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight"><ServerIcon className="h-6 w-6" /> MCP Servers</h1>
          <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">
            Tool servers the agents in your apps may call. Register one here and it can be picked in any Agent Builder tool node as an
            “MCP Server Tool”. Secrets are encrypted and never shown again.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {servers.length > 0 && <span className="text-sm text-muted-foreground">{on} of {servers.length} enabled</span>}
          <Button onClick={openAdd} data-testid="add-server-button"><Plus className="mr-1 h-4 w-4" />Add Server</Button>
        </div>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : servers.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center dark:border-slate-700 dark:bg-slate-900">
          <span className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-slate-100 text-slate-500 dark:bg-slate-800"><Plug className="h-6 w-6" /></span>
          <p className="mt-4 text-sm font-medium">No MCP servers registered</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
            An MCP server gives your agents tools — search the web, read a CRM, send a message — over one protocol. Add one and every agent in the organisation can use it.
          </p>
          <Button variant="outline" size="sm" className="mt-5" onClick={openAdd}><Plus className="mr-1 h-3.5 w-3.5" />Add your first server</Button>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {servers.map((s) => {
            const test = testResults[s.id];
            return (
              <div key={s.id} data-testid={`server-row-${s.id}`} data-server-card=""
                   className={`flex flex-col rounded-xl border bg-white p-5 shadow-sm dark:bg-slate-900 ${s.enabled ? "border-slate-200 dark:border-slate-800" : "border-dashed border-slate-300 opacity-80 dark:border-slate-700"}`}>
                <div className="flex items-start justify-between gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200"><ServerIcon className="h-5 w-5" /></span>
                  {s.enabled
                    ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20 dark:bg-emerald-950/40 dark:text-emerald-300"><Check className="h-3 w-3" />Enabled</span>
                    : <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 ring-1 ring-inset ring-slate-500/20 dark:bg-slate-800 dark:text-slate-300">Disabled</span>}
                </div>
                <h3 className="mt-4 text-[15px] font-semibold text-slate-900 dark:text-white">{s.name}</h3>
                <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground" title={s.server_url}>{s.server_url}</p>
                <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                  <dt className="text-muted-foreground">Transport</dt><dd className="text-right text-slate-700 dark:text-slate-200">{title(TRANSPORTS, s.transport)}</dd>
                  <dt className="text-muted-foreground">Authentication</dt>
                  <dd className="text-right text-slate-700 dark:text-slate-200">{title(AUTH_KINDS, s.auth_kind)}{s.auth_kind === "apikey_header" && s.auth_header_name ? ` · ${s.auth_header_name}` : ""}</dd>
                </dl>
                <div className="mt-4 flex min-h-6 items-center text-xs">
                  {test === "pending" && <span className="inline-flex items-center gap-1 text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />Trying…</span>}
                  {test && test !== "pending" && test.ok && (
                    <span data-testid={`test-ok-${s.id}`} className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20 dark:bg-emerald-950/40 dark:text-emerald-300">
                      <Check className="h-3 w-3" />Answered · {test.tool_count ?? 0} tool{test.tool_count === 1 ? "" : "s"}
                    </span>
                  )}
                  {test && test !== "pending" && !test.ok && (
                    <span data-testid={`test-err-${s.id}`} className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 font-medium text-red-700 ring-1 ring-inset ring-red-600/20 dark:bg-red-950/40 dark:text-red-300" title={test.error}>
                      <XIcon className="h-3 w-3" />Did not answer
                    </span>
                  )}
                  {!test && <span className="text-muted-foreground">Not tried yet</span>}
                </div>
                <div className="mt-4 flex items-center justify-between gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
                  <Button variant="outline" size="sm" onClick={() => runTest(s)} disabled={test === "pending"} data-testid={`test-button-${s.id}`}>
                    <Plug className="mr-1.5 h-3.5 w-3.5" />Test
                  </Button>
                  <div className="flex items-center gap-1">
                    <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openEdit(s)} title="Edit"><Pencil className="h-3.5 w-3.5" /></Button>
                    <Button variant="ghost" size="icon" className="h-8 w-8" title="Remove"
                            onClick={() => { if (window.confirm(`Remove MCP server "${s.name}"? Agents still referencing it will fail at runtime.`)) remove.mutate(s.id); }}>
                      <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? `Edit ${editing.name}` : "Add an MCP server"}</DialogTitle>
            <DialogDescription>{editing ? "Change how the server is reached. The secret stays unless you type a new one." : "Where the server is and how to authenticate to it."}</DialogDescription>
          </DialogHeader>
          <McpServerForm orgId={orgId} server={editing} onClose={() => setDialogOpen(false)} invalidateKey={invalidateKey} />
        </DialogContent>
      </Dialog>
    </div>
  );
}

function McpServerForm({ orgId, server, onClose, invalidateKey }: { orgId: string; server: McpServer | null; onClose: () => void; invalidateKey: readonly unknown[] }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<McpServerFormValues>(
    server ? { name: server.name, server_url: server.server_url, transport: server.transport, auth_kind: server.auth_kind,
               auth_secret: "", auth_header_name: server.auth_header_name ?? "", enabled: server.enabled } : emptyForm(),
  );
  const [showSecretText, setShowSecretText] = useState(false);

  const mutation = useMutation({
    mutationFn: async () => {
      // Optional fields are sent only when they carry something; a blank
      // secret on an edit keeps the one on record.
      const payload: Record<string, unknown> = { name: form.name, server_url: form.server_url, transport: form.transport, auth_kind: form.auth_kind, enabled: form.enabled };
      if (form.auth_kind === "apikey_header" && form.auth_header_name) payload.auth_header_name = form.auth_header_name;
      if (form.auth_kind !== "none" && form.auth_secret) payload.auth_secret = form.auth_secret;
      if (server) return api.put<McpServer>(`/api/orgs/${orgId}/mcp-servers/${server.id}`, payload);
      return api.post<McpServer>(`/api/orgs/${orgId}/mcp-servers`, payload);
    },
    onSuccess: () => { toast.success(server ? "Server updated." : "Server registered."); queryClient.invalidateQueries({ queryKey: invalidateKey }); onClose(); },
    onError: (err: unknown) => toast.error(`Save failed: ${err instanceof Error ? err.message : "unknown error"}`),
  });

  const needsSecret = form.auth_kind !== "none";
  const needsHeaderName = form.auth_kind === "apikey_header";
  const chosenTransport = TRANSPORTS.find((t) => t.value === form.transport);
  const chosenAuth = AUTH_KINDS.find((a) => a.value === form.auth_kind);

  return (
    <form onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
      <div className="space-y-4 py-2">
        <div className="space-y-1.5">
          <Label htmlFor="mcp-name">Name</Label>
          <Input id="mcp-name" required placeholder="e.g. Firecrawl" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <p className="text-xs text-muted-foreground">What agents and people will see it called.</p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="mcp-url">Server URL</Label>
          <Input id="mcp-url" required type="url" placeholder="https://mcp.example.com/mcp" value={form.server_url} onChange={(e) => setForm({ ...form, server_url: e.target.value })} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label>Transport</Label>
            <Select value={form.transport} onValueChange={(v) => setForm({ ...form, transport: v as McpTransport })}>
              <SelectTrigger data-testid="transport-select"><SelectValue /></SelectTrigger>
              <SelectContent>{TRANSPORTS.map((t) => <SelectItem key={t.value} value={t.value}>{t.title}</SelectItem>)}</SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{chosenTransport?.hint}</p>
          </div>
          <div className="space-y-1.5">
            <Label>Authentication</Label>
            <Select value={form.auth_kind} onValueChange={(v) => setForm({ ...form, auth_kind: v as McpAuthKind })}>
              <SelectTrigger data-testid="auth-select"><SelectValue /></SelectTrigger>
              <SelectContent>{AUTH_KINDS.map((a) => <SelectItem key={a.value} value={a.value}>{a.title}</SelectItem>)}</SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{chosenAuth?.hint}</p>
          </div>
        </div>
        {needsHeaderName && (
          <div className="space-y-1.5">
            <Label htmlFor="mcp-header">Header name</Label>
            <Input id="mcp-header" placeholder="X-API-Key" value={form.auth_header_name} onChange={(e) => setForm({ ...form, auth_header_name: e.target.value })} />
          </div>
        )}
        {needsSecret && (
          <div className="space-y-1.5">
            <Label htmlFor="mcp-secret" className="flex items-center gap-1.5"><KeyRound className="h-3.5 w-3.5" />{form.auth_kind === "bearer" ? "Token" : "API key"}
              {server && <span className="ml-1 text-xs font-normal text-muted-foreground">leave blank to keep the current one</span>}
            </Label>
            <div className="relative">
              <Input id="mcp-secret" type={showSecretText ? "text" : "password"} autoComplete="new-password" className="pr-9"
                     placeholder={server ? "••••••••" : form.auth_kind === "bearer" ? "The bearer token" : "The key"}
                     value={form.auth_secret} onChange={(e) => setForm({ ...form, auth_secret: e.target.value })} />
              <button type="button" aria-label={showSecretText ? "Hide" : "Show"} onClick={() => setShowSecretText((v) => !v)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                {showSecretText ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>
        )}
        <div className="flex items-center justify-between rounded-lg border p-3">
          <div>
            <Label className="text-sm">Enabled</Label>
            <p className="text-xs text-muted-foreground">A disabled server stays registered but is not offered to agents.</p>
          </div>
          <Switch checked={form.enabled} onCheckedChange={(v: boolean) => setForm({ ...form, enabled: v })} data-testid="enabled-switch" />
        </div>
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose} disabled={mutation.isPending}>Cancel</Button>
        <Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? "Saving…" : server ? "Save" : "Register"}</Button>
      </DialogFooter>
    </form>
  );
}

export default function McpServersSettingsPage({ params }: { params: Promise<{ orgId: string }> }) {
  const { orgId } = use(params);
  return <McpServersSettings orgId={orgId} />;
}
