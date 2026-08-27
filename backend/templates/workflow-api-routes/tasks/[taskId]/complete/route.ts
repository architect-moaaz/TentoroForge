/** POST /api/workflows/tasks/[taskId]/complete — complete a task. */

import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import { WorkflowEngine } from '@/lib/workflow-engine';

export async function POST(
  request: NextRequest,
  { params }: { params: { taskId: string } },
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: { code: 'UNAUTHORIZED', message: 'Not authenticated' } }, { status: 401 });
  }

  try {
    const body = await request.json();
    const { outputData } = body;

    const engine = new WorkflowEngine();
    const task = await engine.completeTask(params.taskId, outputData);

    return NextResponse.json(task);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Failed to complete task';
    return NextResponse.json({ error: { code: 'BAD_REQUEST', message } }, { status: 400 });
  }
}
