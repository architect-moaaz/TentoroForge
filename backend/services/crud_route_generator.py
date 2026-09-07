"""Deterministic CRUD API-route generator (working-app reliability).

The api agent runs on the bundled CLI and frequently wedges at the 600s timeout,
leaving most entities with a DB schema but NO API routes — so the generated app can't
list/create/edit that data. This module fills the gap deterministically from the schema
files: for every `src/db/schema/<entity>.ts` it ensures the standard route set exists
(`/api/<slug>/route.ts`, `[id]/route.ts`, `stats/route.ts`). It is NON-DESTRUCTIVE —
it never overwrites a route the LLM already wrote (those may carry custom logic), it
only creates the missing ones. Can't time out; guarantees a working data layer.
"""
from __future__ import annotations

import re
from pathlib import Path

_PGTABLE_RE = re.compile(r'export\s+const\s+(\w+)\s*=\s*pgTable\(\s*["\']([^"\']+)["\']')
_ID_NUMERIC_RE = re.compile(r'\bid:\s*(serial|integer|bigint|smallint)\b')


def parse_schema_file(text: str) -> dict | None:
    """Extract {export, table, id_numeric} from a Drizzle schema file, or None."""
    m = _PGTABLE_RE.search(text)
    if not m:
        return None
    return {"export": m.group(1), "table": m.group(2),
            "id_numeric": bool(_ID_NUMERIC_RE.search(text))}


def slug_for(table_name: str) -> str:
    """URL slug from a snake_case table name: work_orders -> work-orders."""
    return table_name.replace("_", "-")


_LIST = """import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { db } from "@/db";
import { __TABLE__ } from "@/db/schema";

// Auto-generated CRUD route (deterministic completeness fill).
export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  try {
    const data = await db.select().from(__TABLE__);
    return NextResponse.json({ data, total: data.length });
  } catch (error) {
    return NextResponse.json({ data: [], total: 0 });
  }
}

export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  try {
    const body = await request.json();
    const [created] = await db.insert(__TABLE__).values(body).returning();
    return NextResponse.json(created, { status: 201 });
  } catch (error) {
    return NextResponse.json({ error: "Failed to create" }, { status: 400 });
  }
}
"""

_BYID = """import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { db } from "@/db";
import { __TABLE__ } from "@/db/schema";
import { eq } from "drizzle-orm";

// Auto-generated CRUD route (deterministic completeness fill).
export async function GET(_request: Request, { params }: { params: { id: string } }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const id = __ID__;
    const [row] = await db.select().from(__TABLE__).where(eq(__TABLE__.id, id as any));
    if (!row) return NextResponse.json({ error: "Not found" }, { status: 404 });
    return NextResponse.json(row);
  } catch (error) {
    return NextResponse.json({ error: "Failed to fetch" }, { status: 500 });
  }
}

export async function PUT(request: Request, { params }: { params: { id: string } }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const id = __ID__;
    const body = await request.json();
    const [updated] = await db.update(__TABLE__).set(body).where(eq(__TABLE__.id, id as any)).returning();
    if (!updated) return NextResponse.json({ error: "Not found" }, { status: 404 });
    return NextResponse.json(updated);
  } catch (error) {
    return NextResponse.json({ error: "Failed to update" }, { status: 400 });
  }
}

export async function DELETE(_request: Request, { params }: { params: { id: string } }) {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const id = __ID__;
    await db.delete(__TABLE__).where(eq(__TABLE__.id, id as any));
    return NextResponse.json({ success: true });
  } catch (error) {
    return NextResponse.json({ error: "Failed to delete" }, { status: 400 });
  }
}
"""

_STATS = """import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { db } from "@/db";
import { __TABLE__ } from "@/db/schema";
import { sql } from "drizzle-orm";

// Auto-generated CRUD route (deterministic completeness fill).
export async function GET() {
  const session = await auth();
  if (!session?.user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const [row] = await db.select({ count: sql<number>`count(*)` }).from(__TABLE__);
    return NextResponse.json({ count: Number(row?.count ?? 0) });
  } catch (error) {
    return NextResponse.json({ count: 0 });
  }
}
"""


def _render(tmpl: str, export: str, id_numeric: bool) -> str:
    coerce = "Number(params.id)" if id_numeric else "params.id"
    return tmpl.replace("__TABLE__", export).replace("__ID__", coerce)


def ensure_api_routes(output_dir: str | Path) -> list[str]:
    """Fill missing CRUD routes for every entity that has a schema file.

    Returns the list of files written (empty if everything already existed).
    Non-destructive: only writes a route file that does not yet exist.
    """
    root = Path(output_dir)
    schema_dir = root / "src" / "db" / "schema"
    api_dir = root / "src" / "app" / "api"
    written: list[str] = []
    if not schema_dir.exists():
        return written

    for sf in sorted(schema_dir.glob("*.ts")):
        if sf.name == "index.ts":
            continue
        info = parse_schema_file(sf.read_text(encoding="utf-8"))
        if not info:
            continue
        exp, id_num = info["export"], info["id_numeric"]
        edir = api_dir / slug_for(info["table"])

        targets = [
            (edir / "route.ts", _LIST),
            (edir / "[id]" / "route.ts", _BYID),
            (edir / "stats" / "route.ts", _STATS),
        ]
        for path, tmpl in targets:
            if path.exists():
                continue  # keep the LLM's version — may have custom logic
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_render(tmpl, exp, id_num), encoding="utf-8")
            written.append(str(path))
    return written
