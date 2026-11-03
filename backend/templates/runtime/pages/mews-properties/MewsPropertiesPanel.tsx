"use client";
import * as React from "react";
import { useRouter } from "next/navigation";
import { apiPath } from "@/lib/api-path";

type Property = {
  id: string;
  name: string;
  enterpriseId: string | null;
  environment: "demo" | "production";
  tokenMask: string | null;
  hasToken: boolean;
  enterpriseName: string | null;
  checkedAt: string | null;
  checkOk: boolean | null;
  checkMessage: string | null;
};

type Draft = { name: string; enterpriseId: string; environment: "demo" | "production"; accessToken: string };
const EMPTY: Draft = { name: "", enterpriseId: "", environment: "demo", accessToken: "" };

export function MewsPropertiesPanel({ properties }: { properties: Property[] }) {
  const router = useRouter();
  const [draft, setDraft] = React.useState<Draft>(EMPTY);
  const [editing, setEditing] = React.useState<string | null>(null);
  const [said, setSaid] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function call(path: string, method: string, body?: Record<string, unknown>): Promise<boolean> {
    setBusy(true);
    setSaid(null);
    try {
      const res = await fetch(apiPath(path), {
        method,
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok) { setSaid(out.error ?? `Something went wrong (${res.status}).`); return false; }
      if (out.property?.checkMessage && path.endsWith("/check")) setSaid(out.property.checkMessage);
      router.refresh();
      return true;
    } finally {
      setBusy(false);
    }
  }

  function startEdit(p: Property) {
    setEditing(p.id);
    setDraft({ name: p.name, enterpriseId: p.enterpriseId ?? "", environment: p.environment, accessToken: "" });
    setSaid(null);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = { name: draft.name, enterpriseId: draft.enterpriseId, environment: draft.environment };
    // A blank token field keeps the stored token; only something typed replaces it.
    if (draft.accessToken.trim()) body.accessToken = draft.accessToken.trim();
    const done = editing
      ? await call(`/api/mews/properties/${editing}`, "PATCH", body)
      : await call("/api/mews/properties", "POST", body);
    if (done) { setDraft(EMPTY); setEditing(null); }
  }

  const field = "rounded border border-border px-2 py-1 bg-background w-full";

  return (
    <div>
      <ul className="divide-y divide-border rounded-md border border-border mb-6">
        {properties.map((p) => (
          <li key={p.id} className="flex flex-wrap items-start justify-between gap-3 p-3 text-sm">
            <div className="min-w-0">
              <div className="font-medium">{p.name}</div>
              <div className="text-muted-foreground">
                {p.environment === "production" ? "Production" : "Demo"}
                {p.enterpriseId ? ` · enterprise ${p.enterpriseId}` : ""}
                {" · "}
                {p.hasToken ? `token ${p.tokenMask ?? "set"}` : "portfolio token"}
              </div>
              {p.checkedAt && (
                <div className={p.checkOk ? "text-emerald-600" : "text-destructive"}>
                  {p.checkMessage} <span className="text-muted-foreground">({new Date(p.checkedAt).toLocaleString()})</span>
                </div>
              )}
            </div>
            <div className="flex gap-2">
              <button className="rounded border border-border px-2 py-1" disabled={busy}
                      onClick={() => void call(`/api/mews/properties/${p.id}/check`, "POST")}>Check connection</button>
              <button className="rounded border border-border px-2 py-1" disabled={busy} onClick={() => startEdit(p)}>Edit</button>
              <button className="rounded border border-border px-2 py-1 text-destructive" disabled={busy}
                      onClick={() => { if (confirm(`Remove ${p.name}? The application stops reaching it in Mews, and its token is deleted.`)) void call(`/api/mews/properties/${p.id}`, "DELETE"); }}>
                Remove
              </button>
            </div>
          </li>
        ))}
        {properties.length === 0 && <li className="p-6 text-center text-muted-foreground">No property yet. Add the first below.</li>}
      </ul>

      <form className="grid gap-3 sm:grid-cols-2 rounded-md border border-border p-4" onSubmit={save}>
        <div className="sm:col-span-2 font-medium">{editing ? "Change property" : "Add a property"}</div>
        <label className="text-sm">Name
          <input className={field} value={draft.name} required onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        </label>
        <label className="text-sm">Environment
          <select className={field} value={draft.environment}
                  onChange={(e) => setDraft({ ...draft, environment: e.target.value === "production" ? "production" : "demo" })}>
            <option value="demo">Demo</option>
            <option value="production">Production</option>
          </select>
        </label>
        <label className="text-sm">Enterprise id <span className="text-muted-foreground">(needed with a portfolio token)</span>
          <input className={field} value={draft.enterpriseId} placeholder="e.g. 851df8c8-90f2-4c4a-8e01-a4fc46b25178"
                 onChange={(e) => setDraft({ ...draft, enterpriseId: e.target.value })} />
        </label>
        <label className="text-sm">Access token
          <input className={field} type="password" autoComplete="off" value={draft.accessToken}
                 placeholder={editing ? "•••••••• — leave blank to keep" : "The property's access token"}
                 onChange={(e) => setDraft({ ...draft, accessToken: e.target.value })} />
        </label>
        <div className="sm:col-span-2 flex flex-wrap gap-2">
          <button type="submit" disabled={busy} className="rounded bg-primary text-primary-foreground px-3 py-1">
            {editing ? "Save" : "Add property"}
          </button>
          {editing && (
            <>
              <button type="button" className="rounded border border-border px-3 py-1" disabled={busy}
                      onClick={() => { setEditing(null); setDraft(EMPTY); }}>Cancel</button>
              <button type="button" className="rounded border border-border px-3 py-1" disabled={busy}
                      onClick={async () => { if (confirm("Remove this property's own token? It will be reached with the portfolio token.") && await call(`/api/mews/properties/${editing}`, "PATCH", { accessToken: null })) { setEditing(null); setDraft(EMPTY); } }}>
                Remove its token
              </button>
            </>
          )}
        </div>
      </form>
      {said && <p className="text-sm mt-3" role="status">{said}</p>}
    </div>
  );
}
