/** POST /api/workflows — start a workflow; GET — list instances. */

import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { db } from '@/db';
import { eq, and, desc } from 'drizzle-orm';
import { wfInstances } from '@/lib/workflow-engine/infrastructure/schema';
import { WorkflowEngine } from '@/lib/workflow-engine';

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: { code: 'UNAUTHORIZED', message: 'Not authenticated' } }, { status: 401 });
  }

  try {
    const body = await request.json();
    const { workflowId, variables } = body;

    if (!workflowId) {
      return NextResponse.json({ error: { code: 'BAD_REQUEST', message: 'workflowId is required' } }, { status: 400 });
    }

    const engine = new WorkflowEngine();
    const instance = await engine.startWorkflow(
      workflowId,
      variables ?? {},
      (session.user as any).id?.toString(),
    );

    return NextResponse.json(instance, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Failed to start workflow';
    return NextResponse.json({ error: { code: 'INTERNAL_ERROR', message } }, { status: 500 });
  }
}

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: { code: 'UNAUTHORIZED', message: 'Not authenticated' } }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const status = searchParams.get('status');
  const workflowId = searchParams.get('workflowId');

  const conditions = [];
  if (status) conditions.push(eq(wfInstances.status, status));
  if (workflowId) conditions.push(eq(wfInstances.workflowId, workflowId));

  const instances = await db
    .select()
    .from(wfInstances)
    .where(conditions.length > 0 ? and(...conditions) : undefined)
    .orderBy(desc(wfInstances.createdAt));

  return NextResponse.json(instances);
}
