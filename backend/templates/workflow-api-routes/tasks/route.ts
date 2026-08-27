/** GET /api/workflows/tasks — list tasks with optional filters. */

import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { db } from '@/db';
import { eq, and, desc } from 'drizzle-orm';
import { wfTaskInstances } from '@/lib/workflow-engine/infrastructure/schema';

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: { code: 'UNAUTHORIZED', message: 'Not authenticated' } }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const assigneeId = searchParams.get('assigneeId');
  const status = searchParams.get('status');

  const conditions = [];
  if (assigneeId) conditions.push(eq(wfTaskInstances.assigneeId, assigneeId));
  if (status) conditions.push(eq(wfTaskInstances.status, status));

  const tasks = await db
    .select()
    .from(wfTaskInstances)
    .where(conditions.length > 0 ? and(...conditions) : undefined)
    .orderBy(desc(wfTaskInstances.createdAt));

  return NextResponse.json(tasks);
}
