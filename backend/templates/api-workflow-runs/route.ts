/**
 * GET /api/workflow-runs
 *
 * Returns the most recent execution-log rows for a node, ordered
 * newest-first. Powers the platform editor's Properties-panel History
 * tab (per spec 2026-07-22-workflow-node-contracts.md § NC-5).
 *
 * Query params
 *   workflow_id — filter to a workflow (id or slug)
 *   node_id     — filter to a specific node (recommended for the panel)
 *   limit       — default 20, max 100
 *
 * Auth: no gate — this is dev/debug data. Callers running behind auth
 * should proxy through their own middleware.
 */

import { NextResponse } from "next/server";
import { db } from "@/db";
import * as schema from "@/db/schema";
import { and, desc, eq, sql } from "drizzle-orm";

export async function GET(req: Request) {
  const wel: any = (schema as any).forgeWorkflowExecutionLog;
  if (!wel) {
    return NextResponse.json(
      { rows: [], error: "workflow_execution_log schema not present" },
      { status: 200 },
    );
  }

  const url = new URL(req.url);
  const workflowId = url.searchParams.get("workflow_id");
  const nodeId = url.searchParams.get("node_id");
  const limitRaw = Number(url.searchParams.get("limit") ?? 20);
  const limit = Math.max(1, Math.min(100, Number.isFinite(limitRaw) ? limitRaw : 20));

  const conds: any[] = [];
  if (workflowId) conds.push(eq(wel.workflowId, workflowId));
  if (nodeId) conds.push(eq(wel.nodeId, nodeId));

  try {
    const query = (db as any).select().from(wel);
    const filtered = conds.length ? query.where(and(...conds)) : query;
    const rows = await filtered.orderBy(desc(wel.createdAt)).limit(limit);
    return NextResponse.json({ rows });
  } catch (err) {
    console.error("[api/workflow-runs] query failed:", err);
    return NextResponse.json(
      { rows: [], error: (err as Error).message },
      { status: 500 },
    );
  }
}
