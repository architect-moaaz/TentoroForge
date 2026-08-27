/**
 * Task Inbox API — returns workflow tasks for the current user.
 *
 * GET /api/tasks?status=pending — filter by status
 *
 * Returns tasks where:
 * - assigneeId matches the logged-in user, OR
 * - assigneeRole matches the user's role, OR
 * - status is "pending" (for admin view)
 */
import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { db } from "@/db";
import { sql } from "drizzle-orm";

export async function GET(request: Request) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const { searchParams } = new URL(request.url);
    const status = searchParams.get("status") || "pending";
    const userId = (session.user as any).id || "";
    const userRole = (session.user as any).role || "";

    // Query tasks assigned to this user by ID, role, or unassigned
    const tasks = await db.execute(sql`
      SELECT * FROM workflow_tasks
      WHERE status = ${status}
        AND (
          assignee_id = ${userId}::text
          OR assignee_role = ${userRole}
          OR (assignee_id IS NULL AND assignee_role IS NULL)
        )
      ORDER BY created_at DESC
      LIMIT 50
    `);

    return NextResponse.json(tasks.rows || []);
  } catch (error) {
    // Table may not exist — return empty
    return NextResponse.json([]);
  }
}
