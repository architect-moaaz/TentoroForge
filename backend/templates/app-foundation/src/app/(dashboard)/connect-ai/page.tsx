"use client";
/**
 * Connect an AI assistant — the person's own way in for Claude or any MCP client.
 *
 * The assistant acts as the person who made the token: it can run what their
 * role can run and read what their role can see. Off unless the app's owner
 * turned it on; then this page says so and offers nothing.
 *
 * Platform file: every app carries it and the platform replaces it.
 */
import * as React from "react";
import { Bot, Check, Copy, KeyRound, Trash2 } from "lucide-react";

const BASE = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");

type Row = { id: string; label: string; last4: string; createdAt: string; lastUsedAt: string | null; revokedAt: string | null };

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "never";
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = React.useState(false);
  return (
    <button type="button" aria-label={label}
      onClick={() => { void navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}
      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border/60 px-2 py-1 text-xs hover:bg-muted/50">
      {done ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />} {done ? "Copied" : "Copy"}
    </button>
  );
}

export default function ConnectAiPage() {
  const [state, setState] = React.useState<"loading" | "off" | "on" | "error">("loading");
  const [rows, setRows] = React.useState<Row[]>([]);
  const [label, setLabel] = React.useState("");
  const [made, setMade] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const endpoint = typeof window === "undefined" ? `${BASE}/api/mcp` : `${window.location.origin}${BASE}/api/mcp`;

  const load = React.useCallback(async () => {
    const res = await fetch(`${BASE}/api/mcp/tokens`, { cache: "no-store" }).catch(() => null);
    if (!res) return setState("error");
    if (res.status === 404) return setState("off");
    if (!res.ok) return setState("error");
    const data = await res.json();
    setRows(data.tokens ?? []);
    setState("on");
  }, []);
  React.useEffect(() => { void load(); }, [load]);

  async function make() {
    setBusy(true);
    try {
      const res = await fetch(`${BASE}/api/mcp/tokens`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ label: label || "AI assistant" }),
      });
      if (res.ok) { setMade((await res.json()).token); setLabel(""); await load(); }
    } finally { setBusy(false); }
  }

  async function revoke(id: string) {
    await fetch(`${BASE}/api/mcp/tokens?id=${encodeURIComponent(id)}`, { method: "DELETE" });
    await load();
  }

  const command = `claude mcp add --transport http this-app ${endpoint} --header "Authorization: Bearer ${made ?? "<your token>"}"`;

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-6">
      <header className="space-y-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold text-foreground"><Bot size={20} aria-hidden /> Connect an AI assistant</h1>
        <p className="text-sm text-muted-foreground">
          Let Claude, or any assistant that speaks MCP, use this app for you. It acts as you: it can run what your role
          can run and see what your role can see — nothing more — and everything it does is recorded as you.
        </p>
      </header>

      {state === "loading" && <p className="text-sm text-muted-foreground">Loading…</p>}
      {state === "error" && <p className="text-sm text-destructive">Could not read your connections. Reload the page to try again.</p>}
      {state === "off" && (
        <p data-mcp-off="" className="rounded-lg border border-border/60 p-4 text-sm text-muted-foreground">
          Connecting AI assistants is turned off for this app. The app&rsquo;s owner can turn it on in the app&rsquo;s settings.
        </p>
      )}

      {state === "on" && (
        <>
          <section className="space-y-2">
            <h2 className="text-sm font-medium text-foreground">The address</h2>
            <div className="flex items-center gap-2 rounded-lg border border-border/60 p-2">
              <code className="min-w-0 flex-1 truncate text-sm">{endpoint}</code>
              <CopyButton text={endpoint} label="Copy the address" />
            </div>
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-foreground">A token for your assistant</h2>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="What it is for, e.g. Claude on my laptop"
                aria-label="What the token is for"
                className="min-w-0 flex-1 rounded-md border border-border/60 bg-background px-3 py-2 text-sm" />
              <button type="button" onClick={make} disabled={busy}
                className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-60">
                <KeyRound size={14} aria-hidden /> Make a token
              </button>
            </div>
            {made && (
              <div data-mcp-token="" className="space-y-2 rounded-lg border border-border/60 bg-muted/30 p-3">
                <p className="text-sm text-foreground">Copy it now — it is not shown again.</p>
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 break-all text-xs">{made}</code>
                  <CopyButton text={made} label="Copy the token" />
                </div>
              </div>
            )}
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-foreground">Add it to your assistant</h2>
            <p className="text-sm text-muted-foreground">
              Any MCP client: the address above, with the header <code>Authorization: Bearer &lt;your token&gt;</code>.
              For Claude Code, run:
            </p>
            <div className="flex items-start gap-2 rounded-lg border border-border/60 p-2">
              <code className="min-w-0 flex-1 break-all text-xs">{command}</code>
              <CopyButton text={command} label="Copy the command" />
            </div>
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-foreground">Your tokens</h2>
            {!rows.length && <p className="text-sm text-muted-foreground">None yet.</p>}
            <ul className="divide-y divide-border/60 rounded-lg border border-border/60">
              {rows.map((r) => (
                <li key={r.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-foreground">{r.label} <span className="text-muted-foreground">…{r.last4}</span></p>
                    <p className="text-xs text-muted-foreground">
                      Made {when(r.createdAt)} · last used {when(r.lastUsedAt)}{r.revokedAt ? ` · revoked ${when(r.revokedAt)}` : ""}
                    </p>
                  </div>
                  {!r.revokedAt && (
                    <button type="button" onClick={() => revoke(r.id)} aria-label={`Revoke ${r.label}`}
                      className="inline-flex items-center gap-1 rounded-md border border-border/60 px-2 py-1 text-xs hover:bg-muted/50">
                      <Trash2 size={12} aria-hidden /> Revoke
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
