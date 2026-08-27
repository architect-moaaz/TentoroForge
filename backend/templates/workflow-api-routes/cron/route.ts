/** POST /api/workflows/cron — timer check endpoint (called by cron or self-invoke interval). */

import { NextResponse } from 'next/server';
import { TimerScheduler } from '@/lib/workflow-engine';

export async function POST() {
  try {
    const scheduler = new TimerScheduler();
    await scheduler.checkExpiredTimers();
    await scheduler.checkSlaBreaches();
    return NextResponse.json({ ok: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Timer check failed';
    console.error('[workflow] Cron timer check failed:', message);
    return NextResponse.json({ ok: false, error: message }, { status: 500 });
  }
}
