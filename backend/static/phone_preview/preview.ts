// The editor's phone preview: the app's backend, in the page, with sample data.
//
// Written into a COPY of the phone project when the preview is built (never into the project itself, never into a
// build that ships). `api.ts` hands every request here; a request for the app's own `/api/*` is answered from
// `preview-data.json` (rows made from the Blueprint's own entities) as a signed-in sample person, and anything else
// (a font, an image) is a real fetch. Nothing is sent anywhere and nothing is kept: a change a screen makes lives
// in memory and is gone on reload.
import data from "./preview-data.json";

type Row = Record<string, unknown>;
type Meta = { rows: Row[]; label: string; numeric: string[] };
const entities = (data as { entities: Record<string, Meta> }).entities;
const user = (data as { user: Row }).user;
const account = (data as { account: string | null }).account;

// Signed in when the preview opens, so a person walks straight into the app. Signing out brings the real sign-in and
// sign-up screens back, and any values let them in again: nothing here is checked against anything.
let signedIn = true;

const store: Record<string, Row[]> = {};
for (const [name, meta] of Object.entries(entities)) store[name] = meta.rows.map((r) => ({ ...r }));

const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function num(v: unknown): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function matches(row: Row, where: Record<string, unknown> | undefined): boolean {
  if (!where) return true;
  return Object.entries(where).every(([k, want]) => {
    if (want && typeof want === "object" && !Array.isArray(want)) return true; // a filter by a related record
    const have = row[k];
    return Array.isArray(want) ? want.map(String).includes(String(have)) : String(have) === String(want);
  });
}

function rowsOf(b: Row): Row[] {
  const rows = store[String(b.entity)] ?? [];
  return rows.filter((r) => matches(r, b.where as Record<string, unknown> | undefined));
}

function aggregate(rows: Row[], fn: string, field?: string): number {
  if (fn === "count" || !field) return rows.length;
  const values = rows.map((r) => num(r[field]));
  if (!values.length) return 0;
  if (fn === "sum") return values.reduce((a, c) => a + c, 0);
  if (fn === "avg") return values.reduce((a, c) => a + c, 0) / values.length;
  if (fn === "min") return Math.min(...values);
  if (fn === "max") return Math.max(...values);
  return rows.length;
}

function list(b: Row) {
  const meta = entities[String(b.entity)];
  let rows = rowsOf(b);
  const q = String(b.search ?? "").trim().toLowerCase();
  if (q) rows = rows.filter((r) => Object.values(r).some((v) => typeof v === "string" && v.toLowerCase().includes(q)));
  const sort = b.sort ? String(b.sort) : "";
  if (sort) {
    const dir = b.order === "desc" ? -1 : 1;
    rows = [...rows].sort((x, y) => (x[sort]! > y[sort]! ? dir : x[sort]! < y[sort]! ? -dir : 0));
  }
  const limit = Math.min(Math.max(num(b.limit) || 50, 1), 200);
  const page = Math.max(num(b.page) || 1, 1);
  void meta;
  return { rows: rows.slice((page - 1) * limit, page * limit), total: rows.length, page, limit };
}

function series(b: Row) {
  const groups = new Map<string, Row[]>();
  for (const r of rowsOf(b)) {
    const key = String(r[String(b.groupBy)] ?? "—");
    groups.set(key, [...(groups.get(key) ?? []), r]);
  }
  return { points: [...groups].map(([label, rows]) => ({ label, value: aggregate(rows, String(b.fn ?? "count"), b.field as string | undefined) })) };
}

function query(b: Row) {
  const measures = (b.measures ?? {}) as Record<string, { fn: string; field?: string }>;
  const dims = (b.dimensions ?? []) as Array<string | { field: string }>;
  const field = dims.length ? (typeof dims[0] === "string" ? dims[0] : dims[0].field) : null;
  const groups = new Map<string, Row[]>();
  for (const r of rowsOf(b)) {
    const key = field ? String(r[field] ?? "—") : "";
    groups.set(key, [...(groups.get(key) ?? []), r]);
  }
  const rows = [...groups].map(([key, rs]) => {
    const out: Row = field ? { [field]: key } : {};
    for (const [name, m] of Object.entries(measures)) out[name] = aggregate(rs, m.fn, m.field);
    return out;
  });
  return { rows };
}

function route(path: string, method: string, body: Row): Response {
  if (path === "/api/auth/session") return reply(signedIn ? { user } : {});
  if (path === "/api/auth/methods") return reply({ password: true, magicLink: false, sso: [] });
  if (path === "/api/auth/csrf") return reply({ csrfToken: "preview" });
  if (path.startsWith("/api/auth/callback")) { signedIn = true; return reply({ url: "/" }); }
  if (path === "/api/auth/signup") return reply({ ok: true });
  if (path.startsWith("/api/auth/signout")) { signedIn = false; return reply({}); }
  if (path.startsWith("/api/auth/")) return reply({});
  if (!signedIn && !path.startsWith("/api/auth/")) return reply({ error: { message: "Sign in to use this." } }, 401);
  if (path === "/api/org") return reply({ organisations: [], activeOrgId: null, platform: false });
  if (path === "/api/read/me") return reply({ user, account: account ? (store[account] ?? [])[0] ?? null : null });
  if (path.startsWith("/api/read/")) {
    const op = path.slice("/api/read/".length);
    if (!entities[String(body.entity)] && op !== "widget" && op !== "me") return reply({ error: `No such entity: ${String(body.entity)}` }, 404);
    if (op === "list") return reply(list(body));
    if (op === "record") {
      const row = (store[String(body.entity)] ?? []).find((r) => String(r.id) === String(body.id));
      return row ? reply({ record: row }) : reply({ error: "Not found." }, 404);
    }
    if (op === "records") {
      const ids = ((body.ids ?? []) as unknown[]).map(String);
      return reply({ records: (store[String(body.entity)] ?? []).filter((r) => ids.includes(String(r.id))) });
    }
    if (op === "count") return reply({ value: rowsOf(body).length });
    if (op === "total") return reply({ value: aggregate(rowsOf(body), String(body.fn), String(body.field)) });
    if (op === "series") return reply(series(body));
    if (op === "query") return reply(query(body));
    if (op === "widget") return reply({ rows: [], value: null });
    if (op === "similar") return reply({ rows: rowsOf(body).slice(0, num(body.limit) || 12).map((r) => ({ ...r, similarity: 80 })), error: null });
    if (op === "near") return reply({ rows: rowsOf(body).slice(0, num(body.limit) || 20) });
  }
  if (/^\/api\/workflows\/[^/]+\/execute$/.test(path) && method === "POST") return reply({ status: "completed", reply: {} });
  if (path === "/api/files/upload") return reply({ id: "preview-file" });
  return reply({ error: { message: "This is not part of the preview." } }, 404);
}

export async function previewFetch(url: string, init?: RequestInit): Promise<Response> {
  let path = "";
  try { path = new URL(url).pathname; } catch { path = url; }
  const at = path.indexOf("/api/");
  if (at < 0) return fetch(url, init);
  let body: Row = {};
  try { body = typeof init?.body === "string" && init.body.startsWith("{") ? JSON.parse(init.body) : {}; } catch { body = {}; }
  return route(path.slice(at), String(init?.method ?? "GET").toUpperCase(), body);
}
