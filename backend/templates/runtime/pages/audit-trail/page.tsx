/**
 * The audit trail — who did what, when, before and after. Rendered for the
 * reviewers the audit policy names; everyone else is told it is theirs.
 * Written to the route the Blueprint declares for its `audit_trail` page by
 * the projection (`project_audit`). Forge runtime — do not edit by hand.
 */
import Link from "next/link";
import { cookies, headers } from "next/headers";

export const dynamic = "force-dynamic";

type Row = { seq: number; at: string; actor_id: string | null; actor_role: string | null; actor_kind: string; via: string;
  action: string; entity: string; entity_id: string | null; before: unknown; after: unknown; changed: string[] | null;
  reason: string | null };

async function read(query: string): Promise<{ rows: Row[]; total: number; error?: string; status: number }> {
  const cookieHeader = (await cookies()).getAll().map((c) => `${c.name}=${c.value}`).join("; ");
  const host = (await headers()).get("host") || "localhost:3000";
  const proto = (await headers()).get("x-forwarded-proto") || "http";
  try {
    const res = await fetch(`${proto}://${host}/api/audit${query}`, { headers: { cookie: cookieHeader }, cache: "no-store" });
    const body = await res.json().catch(() => ({}));
    return { rows: body.rows ?? [], total: body.total ?? 0, error: body.error, status: res.status };
  } catch (err) {
    return { rows: [], total: 0, error: String(err), status: 0 };
  }
}

function diff(before: unknown, after: unknown, changed: string[] | null): string {
  const a = (before && typeof before === "object" ? before : {}) as Record<string, unknown>;
  const b = (after && typeof after === "object" ? after : {}) as Record<string, unknown>;
  const cols = changed && changed.length ? changed : Object.keys({ ...a, ...b }).slice(0, 6);
  return cols.map((c) => `${c}: ${JSON.stringify(a[c] ?? null)} → ${JSON.stringify(b[c] ?? null)}`).join("; ");
}

export default async function AuditTrailPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const get = (k: string) => (Array.isArray(sp[k]) ? String(sp[k]?.[0] ?? "") : String(sp[k] ?? ""));
  const filters = ["entity", "entityId", "actor", "action", "from", "to", "page"].filter((k) => get(k));
  const query = filters.length ? "?" + filters.map((k) => `${k}=${encodeURIComponent(get(k))}`).join("&") : "";
  const out = await read(query);
  const page = Math.max(Number(get("page") || 1), 1);
  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-semibold mb-1">Audit trail</h1>
      <p className="text-sm text-muted-foreground mb-4">Who did what, when — before and after. Every row is kept as written.</p>
      {out.status === 403 || out.status === 401 || out.status === 404 ? (
        <div className="rounded-md border border-border p-8 text-center text-muted-foreground">{out.error}</div>
      ) : (
        <>
          <form method="get" className="flex flex-wrap gap-2 mb-4 text-sm">
            <input name="entity" defaultValue={get("entity")} placeholder="Record type" className="rounded border border-border px-2 py-1" />
            <input name="entityId" defaultValue={get("entityId")} placeholder="Record id" className="rounded border border-border px-2 py-1" />
            <input name="actor" defaultValue={get("actor")} placeholder="Person id" className="rounded border border-border px-2 py-1" />
            <input name="action" defaultValue={get("action")} placeholder="Action" className="rounded border border-border px-2 py-1" />
            <input name="from" type="date" defaultValue={get("from")} className="rounded border border-border px-2 py-1" />
            <input name="to" type="date" defaultValue={get("to")} className="rounded border border-border px-2 py-1" />
            <button type="submit" className="rounded bg-primary text-primary-foreground px-3 py-1">Filter</button>
            <a href="/api/audit/export" className="rounded border border-border px-3 py-1">Export CSV</a>
            <a href="/api/audit/verify" className="rounded border border-border px-3 py-1">Verify</a>
          </form>
          <p className="text-xs text-muted-foreground mb-2">{out.total} entries</p>
          {out.rows.length === 0 ? (
            <div className="rounded-md border border-border p-8 text-center text-muted-foreground">Nothing on the record yet.</div>
          ) : (
            <table className="w-full text-sm border border-border rounded-md">
              <thead className="bg-muted/40 text-left"><tr>
                <th className="p-2">When</th><th className="p-2">Who</th><th className="p-2">Did</th><th className="p-2">To</th><th className="p-2">Change</th><th className="p-2">Why</th>
              </tr></thead>
              <tbody>
                {out.rows.map((r) => (
                  <tr key={r.seq} className="border-t border-border align-top">
                    <td className="p-2 whitespace-nowrap">{new Date(r.at).toLocaleString()}</td>
                    <td className="p-2">{r.actor_id ? `${r.actor_role ?? ""} ${r.actor_id.slice(0, 8)}` : r.actor_kind}<div className="text-xs text-muted-foreground">{r.via}</div></td>
                    <td className="p-2">{r.action}</td>
                    <td className="p-2">{r.entity}{r.entity_id ? ` · ${String(r.entity_id).slice(0, 8)}` : ""}</td>
                    <td className="p-2 text-xs break-all">{r.action === "update" || r.action === "create" || r.action === "delete" ? diff(r.before, r.after, r.changed) : ""}</td>
                    <td className="p-2">{r.reason ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="flex gap-2 mt-3 text-sm">
            {page > 1 && <Link href={`?${filters.filter((k) => k !== "page").map((k) => `${k}=${encodeURIComponent(get(k))}`).concat([`page=${page - 1}`]).join("&")}`}>Newer</Link>}
            {out.total > page * 50 && <Link href={`?${filters.filter((k) => k !== "page").map((k) => `${k}=${encodeURIComponent(get(k))}`).concat([`page=${page + 1}`]).join("&")}`}>Older</Link>}
          </div>
        </>
      )}
    </div>
  );
}
