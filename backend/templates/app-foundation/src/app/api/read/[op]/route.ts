/**
 * /api/read/<op> — what a page reads, over HTTP, for a client that is not a
 * page: a phone app has no `load.ts` and cannot import the server half of the
 * SDK. Each op is ONE FUNCTION OF THAT SDK (`@/sdk/server`), called as the
 * signed-in person and answered in the shape the page gets it in — so the
 * ownership and tenancy rules scope a read exactly as they scope the web's,
 * a credential never leaves, numbers are numbers and dates are ISO strings.
 * Nothing is read here that a page could not read; nothing is reimplemented.
 *
 *   POST /api/read/list     { entity, where?, search?, sort?, order?, limit?, page? }  -> { rows, total, page, limit }
 *   POST /api/read/record   { entity, id }                                             -> { record }          (404: not there, or not yours)
 *   POST /api/read/records  { entity, ids }                                            -> { records: { <id>: row } }
 *   POST /api/read/count    { entity, where? }                                         -> { value }
 *   POST /api/read/total    { entity, fn, field, where? }                              -> { value }
 *   POST /api/read/series   { entity, groupBy, bucket?, fn?, field? }                  -> { points }
 *   POST /api/read/query    { entity, measures, dimensions?, where?, range?, ... }     -> { rows }
 *   POST /api/read/widget   { id, range?, where? }                                     -> { rows, value, previous?, delta? }
 *   POST /api/read/similar  { entity, image?, text?, field?, limit? }                  -> { rows, error }
 *   POST /api/read/near     { entity, field, from?, where?, radiusKm?, limit?, scan? } -> { rows }
 *   GET  /api/read/me                                                                  -> { user, account }
 *
 * WHO MAY READ WHAT: the people who may open a page that reads it (`READ_ACCESS`, from the Blueprint): an entity or
 * widget outside that set is a 403 (a 401 with no session), and a column that is not one of the entity's own typed
 * columns (`READABLE_FIELDS`: a hidden one such as a password hash is not) is a 400 wherever a name can be sent: where,
 * sort, groupBy, field, dimensions, measures, timeField. Ownership and tenancy then scope the rows, as on the web.
 *
 * Reads only: a change is a workflow. Forge runtime — do not remove.
 */
import { NextResponse } from "next/server";
import * as sdk from "@/sdk/server";
import { READABLE_FIELDS, READ_ACCESS, type ReadAccess } from "@/sdk/schema";
import { widgets } from "@/sdk/widgets";
import { isPoint, parseNear } from "@/sdk/geo";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Body = Record<string, unknown>;

const fail = (status: number, code: string, message: string) =>
  NextResponse.json({ error: { code, message } }, { status });

/** An entity the application has. The SDK's own list of columns is the list of
 *  entities; a name that is not an own key of it is not one (`constructor`). */
function entityOf(body: Body): string | null {
  const name = typeof body.entity === "string" ? body.entity : "";
  return name && Object.prototype.hasOwnProperty.call(READABLE_FIELDS, name) ? name : null;
}

/** May this person read it? Anyone, any signed-in person, or the roles the pages that read it are for. */
function mayRead(access: ReadAccess | undefined, user: { role: string | null } | null): boolean {
  if (!access) return false;
  if (access.anyone) return true;
  if (!user) return false;
  return access.signedIn || (user.role !== null && access.roles.includes(user.role));
}

const refused = (user: unknown) =>
  user ? fail(403, "FORBIDDEN", "You cannot read this.") : fail(401, "UNAUTHENTICATED", "Sign in to read this.");

/** The first name that is not one of the entity's own readable columns, if any. A hidden column (a password hash, an
 *  encrypted value) is not in the list, so it cannot be probed by equality, ordering or grouping. */
function unknownColumn(entity: string, names: readonly unknown[]): string | undefined {
  const known = READABLE_FIELDS[entity] ?? [];
  for (const n of names) if (typeof n === "string" && n && !known.includes(n)) return n;
  return undefined;
}

const keysOf = (v: unknown): string[] => Object.keys(obj(v) ?? {});
const badColumn = (name: string) => fail(400, "BAD_REQUEST", `${name} is not a field of this entity.`);

const str = (v: unknown): string | undefined => (typeof v === "string" && v ? v : undefined);
const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const obj = (v: unknown): Record<string, unknown> | undefined =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : undefined;

const AGGREGATES = ["sum", "avg", "min", "max"] as const;
const SERIES_FNS = ["count", "sum", "avg", "min", "max"] as const;
const BUCKETS = ["day", "week", "month"] as const;
const ORDERS = ["asc", "desc"] as const;
const oneOf = <T extends string>(v: unknown, set: readonly T[]): T | undefined =>
  typeof v === "string" && (set as readonly string[]).includes(v) ? (v as T) : undefined;

/* eslint-disable @typescript-eslint/no-explicit-any */
async function run(op: string, body: Body): Promise<Response> {
  if (op === "me") {
    return NextResponse.json({ user: await sdk.currentUser(), account: await sdk.myAccount() });
  }

  if (op === "widget") {
    const id = str(body.id);
    const widget = Object.values(widgets).find((w) => w.id === id);
    if (!widget) return fail(404, "NOT_FOUND", `There is no widget ${id ?? ""}.`);
    if (!mayRead(READ_ACCESS.widgets[widget.id], await sdk.currentUser())) return refused(await sdk.currentUser());
    const source = (widget as any).source as { entity: string } | undefined;
    const bad = source ? unknownColumn(source.entity, keysOf(body.where)) : undefined;
    if (bad) return badColumn(bad);
    return NextResponse.json(await sdk.runWidget(widget as any, {
      range: obj(body.range) as any, where: obj(body.where) as any,
    }));
  }

  const entity = entityOf(body);
  if (!entity) return fail(404, "UNKNOWN_ENTITY", "There is no such entity.");
  const E = entity as any;
  const user = await sdk.currentUser();
  if (!mayRead(READ_ACCESS.entities[entity], user)) return refused(user);

  switch (op) {
    case "list": {
      const bad = unknownColumn(entity, [...keysOf(body.where), body.sort]);
      if (bad) return badColumn(bad);
      // The SDK clamps the page size (1 to 200) and the page (1 or more).
      const page = await sdk.listPage(E, {
        where: obj(body.where) as any, search: str(body.search), sort: str(body.sort) as any,
        order: oneOf(body.order, ORDERS), limit: num(body.limit), page: num(body.page),
      });
      return NextResponse.json(page);
    }
    case "record": {
      const row = await sdk.record(E, str(body.id));
      return row ? NextResponse.json({ record: row }) : fail(404, "NOT_FOUND", "Not found.");
    }
    case "records": {
      const ids = Array.isArray(body.ids) ? body.ids.filter((i): i is string => typeof i === "string") : [];
      return NextResponse.json({ records: await sdk.recordsById(E, ids) });
    }
    case "count": {
      const bad = unknownColumn(entity, keysOf(body.where));
      if (bad) return badColumn(bad);
      return NextResponse.json({ value: await sdk.count(E, obj(body.where) as any) });
    }
    case "total": {
      const fn = oneOf(body.fn, AGGREGATES);
      const field = str(body.field);
      if (!fn || !field) return fail(400, "BAD_REQUEST", "total needs fn (sum, avg, min or max) and field.");
      const bad = unknownColumn(entity, [field, ...keysOf(body.where)]);
      if (bad) return badColumn(bad);
      return NextResponse.json({ value: await sdk.total(E, fn, field as any, obj(body.where) as any) });
    }
    case "series": {
      const groupBy = str(body.groupBy);
      if (!groupBy) return fail(400, "BAD_REQUEST", "series needs groupBy.");
      const bad = unknownColumn(entity, [groupBy, body.field]);
      if (bad) return badColumn(bad);
      return NextResponse.json({
        points: await sdk.series(E, {
          groupBy: groupBy as any, bucket: oneOf(body.bucket, BUCKETS),
          fn: oneOf(body.fn, SERIES_FNS), field: str(body.field) as any,
        }),
      });
    }
    case "query": {
      const measures = obj(body.measures);
      if (!measures || !Object.keys(measures).length) return fail(400, "BAD_REQUEST", "query needs measures.");
      const dims = (Array.isArray(body.dimensions) ? body.dimensions : []).map((d) => (obj(d) ? obj(d)!.field : d));
      const sortBy = obj(body.sort)?.by;
      const bad = unknownColumn(entity, [
        ...Object.values(measures).map((m) => obj(m)?.field), ...dims, ...keysOf(body.where), body.timeField,
        typeof sortBy === "string" && sortBy in measures ? undefined : sortBy,
      ]);
      if (bad) return badColumn(bad);
      const limit = num(body.limit);
      return NextResponse.json({
        rows: await sdk.query(E, {
          measures: measures as any,
          dimensions: Array.isArray(body.dimensions) ? (body.dimensions as any) : undefined,
          where: obj(body.where) as any, range: obj(body.range) as any,
          timeField: str(body.timeField) as any, sort: obj(body.sort) as any,
          limit: limit === undefined ? undefined : Math.min(Math.max(Math.trunc(limit), 1), 1000),
        }),
      });
    }
    case "similar": {
      const bad = unknownColumn(entity, [body.field]);
      if (bad) return badColumn(bad);
      return NextResponse.json(await sdk.similar(E, {
        image: str(body.image), text: str(body.text), field: str(body.field), limit: num(body.limit),
      }));
    }
    case "near": {
      const field = str(body.field);
      if (!field) return fail(400, "BAD_REQUEST", "near needs the entity's location field.");
      const bad = unknownColumn(entity, [field, ...keysOf(body.where)]);
      if (bad) return badColumn(bad);
      // Where from: "lat,lng", or { lat, lng }; none ranks nothing but still answers.
      const from = typeof body.from === "string" ? parseNear(body.from) : isPoint(body.from) ? body.from : null;
      return NextResponse.json({
        rows: await sdk.near(E, field as any, from, {
          where: obj(body.where) as any, radiusKm: num(body.radiusKm), limit: num(body.limit), scan: num(body.scan),
        }),
      });
    }
    default:
      return fail(404, "UNKNOWN_OP", `There is no read called ${op}.`);
  }
}

export async function POST(request: Request, { params }: { params: Promise<{ op: string }> }): Promise<Response> {
  const { op } = await params;
  const body = await request.json().catch(() => null);
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    return fail(400, "BAD_REQUEST", "Send a JSON object.");
  }
  try {
    return await run(op, body as Body);
  } catch (err) {
    console.error(`[forge:read] ${op} failed:`, err);
    return fail(500, "READ_FAILED", "The read failed.");
  }
}

export async function GET(_request: Request, { params }: { params: Promise<{ op: string }> }): Promise<Response> {
  const { op } = await params;
  if (op !== "me") return fail(405, "METHOD_NOT_ALLOWED", "This read is a POST.");
  try {
    return await run("me", {});
  } catch (err) {
    console.error("[forge:read] me failed:", err);
    return fail(500, "READ_FAILED", "The read failed.");
  }
}
