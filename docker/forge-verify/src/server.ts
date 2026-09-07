/**
 * HTTP surface for the Self-Verify Pass runner.
 *
 * Endpoints:
 *   POST /run           — enqueue a batch, returns { run_id }
 *   GET  /run/:id       — status + RunReport when finished
 *   GET  /run/:id/stream — SSE progress events
 *   GET  /healthz       — liveness
 */
import Fastify from "fastify";
import { pathToFileURL } from "node:url";
import { BrowserPool } from "./browserPool.js";
import { runBatch } from "./orchestrator.js";
import { RunReport, RunRequest } from "./types.js";

const PORT = Number(process.env.PORT || 6600);
const MAX_CONTEXTS = Number(process.env.FORGE_VERIFY_MAX_CONTEXTS || 3);

interface RunState {
  status: "pending" | "running" | "done" | "failed";
  report?: RunReport;
  error?: string;
  events: Array<{ type: string; data: Record<string, unknown>; ts: number }>;
  subscribers: Array<(event: { type: string; data: Record<string, unknown> }) => void>;
}

const runs = new Map<string, RunState>();
const pool = new BrowserPool({ maxContexts: MAX_CONTEXTS });

function makeRunId(): string {
  return `run_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

const app = Fastify({ logger: { level: "info" } });

app.get("/healthz", async () => ({ ok: true, browsers_warm: true }));

app.post("/run", async (req, reply) => {
  const body = req.body as RunRequest;
  if (!body?.project_id || !body?.interactions?.length) {
    reply.code(400);
    return { error: "project_id + interactions required" };
  }
  const run_id = body.run_id || makeRunId();
  const state: RunState = { status: "pending", events: [], subscribers: [] };
  runs.set(run_id, state);

  // Kick off in the background; return immediately with run_id.
  (async () => {
    state.status = "running";
    try {
      const report = await runBatch(
        { ...body, run_id },
        pool,
        {
          onEvent: (type, data) => {
            const ev = { type, data, ts: Date.now() };
            state.events.push(ev);
            for (const s of state.subscribers) s({ type, data });
          },
        },
      );
      state.report = report;
      state.status = "done";
    } catch (err: any) {
      state.error = err?.message || String(err);
      state.status = "failed";
      const ev = { type: "verify.failed", data: { error: state.error }, ts: Date.now() };
      state.events.push(ev);
      for (const s of state.subscribers) s({ type: ev.type, data: ev.data });
    }
  })();

  return { run_id };
});

app.get("/run/:id", async (req, reply) => {
  const { id } = req.params as { id: string };
  const state = runs.get(id);
  if (!state) { reply.code(404); return { error: "not found" }; }
  // JV-27 — derive latest {done,total,currentUrl} from the event log so
  // backend `_on_progress` can publish `verify_progress` to the chip.
  // Renames `current_route`→`currentUrl` to match the frontend contract.
  let progress: { done: number; total: number; currentUrl: string | null } | undefined;
  for (let i = state.events.length - 1; i >= 0; i--) {
    const ev = state.events[i];
    if (ev.type === "verify.progress") {
      progress = {
        done: Number(ev.data.done) || 0,
        total: Number(ev.data.total) || 0,
        currentUrl: (ev.data.current_route as string) || null,
      };
      break;
    }
  }
  return {
    status: state.status,
    report: state.report,
    error: state.error,
    events_count: state.events.length,
    progress,
  };
});

app.get("/run/:id/stream", async (req, reply) => {
  const { id } = req.params as { id: string };
  const state = runs.get(id);
  if (!state) { reply.code(404); return { error: "not found" }; }

  reply.raw.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });

  // Replay past events immediately so a late subscriber catches up.
  for (const ev of state.events) {
    reply.raw.write(`event: ${ev.type}\ndata: ${JSON.stringify(ev.data)}\n\n`);
  }

  if (state.status === "done" || state.status === "failed") {
    reply.raw.end();
    return;
  }

  const sub = (ev: { type: string; data: Record<string, unknown> }) => {
    reply.raw.write(`event: ${ev.type}\ndata: ${JSON.stringify(ev.data)}\n\n`);
    if (ev.type === "verify.done" || ev.type === "verify.failed") reply.raw.end();
  };
  state.subscribers.push(sub);
  req.raw.on("close", () => {
    state.subscribers = state.subscribers.filter((s) => s !== sub);
  });
});

async function main(): Promise<void> {
  await pool.warm();
  await app.listen({ host: "0.0.0.0", port: PORT });
  app.log.info(`forge-verify listening on :${PORT}`);
}

// Only run when invoked as the entrypoint, not on import (tests import types).
// pathToFileURL, not a `file://` template: on Windows argv[1] is a backslashed
// drive path (C:\...\server.ts) while import.meta.url is file:///C:/.../server.ts,
// so the naive comparison never matches and main() silently never runs.
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((err) => {
    app.log.error(err);
    process.exit(1);
  });
}

export { app, pool };
