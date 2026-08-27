/**
 * Orchestrator — runs a batch of Interactions with retry, groups by page,
 * emits a RunReport.
 *
 * Flake handling: each interaction is retried once on failure. If it
 * passes on retry, marked `flaky: true`. The classifier will treat FLAKY
 * as informational, not a fault (spec §5.12).
 */
import { BrowserPool } from "./browserPool.js";
import { runInteraction } from "./runners.js";
import {
  Evidence,
  FaultRaw,
  Interaction,
  RunReport,
  RunRequest,
  emptyEvidence,
} from "./types.js";

interface Progress {
  onEvent: (type: string, data: Record<string, unknown>) => void;
}

/** A cheap heuristic to decide whether Evidence looks like a "pass". The
 *  real classifier lives in Python; here we only need a bool to drive
 *  retry + faults[] filtering. */
function looksLikePass(interaction: Interaction, ev: Evidence): boolean {
  if (ev.timed_out) return false;
  if (ev.status !== null && ev.status >= 400 && ev.status !== 401) {
    // 401 is expected for auth-gated routes; the Python classifier handles
    // whether that's a fault based on requires_auth.
    return false;
  }
  if (interaction.kind === "button" && interaction.action.kind === "workflow") {
    const fired = ev.network_log.some(
      (n) => n.method === "POST" && n.url.includes("/api/workflows/"),
    );
    if (!fired) return false;
  }
  if (interaction.kind === "list" && ev.rows_returned === 0) return false;
  if (interaction.kind === "form") {
    const posts = ev.network_log.filter((n) => n.method === "POST");
    if (posts.length === 0) return false;
    if (posts[posts.length - 1].status >= 400) return false;
  }
  return true;
}


export async function runBatch(
  req: RunRequest, pool: BrowserPool, progress?: Progress,
): Promise<RunReport> {
  const runId = req.run_id || `run_${Date.now().toString(36)}`;
  const startedAt = new Date().toISOString();
  const opts = {
    baseUrl: req.base_url.replace(/\/$/, ""),
    timeoutMs: req.interaction_timeout_ms || 15_000,
    auth: req.auth,
  };
  const faults: FaultRaw[] = [];
  let passed = 0;
  let flaky = 0;

  progress?.onEvent("verify.started", {
    run_id: runId, target: req.target, scope: "*",
    interactions_count: req.interactions.length,
  });

  // Group by route so we don't over-parallelize the same page; each group
  // runs serially against one browser context. Cross-group parallelism is
  // bounded by the pool's semaphore.
  const groups = new Map<string, Interaction[]>();
  for (const it of req.interactions) {
    const key = it.route || "_orphan";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(it);
  }

  // Hard wall-clock cap per interaction — Playwright's action-level timeouts
  // (goto/click/waitForLoadState) usually contain a hang, but a truly wedged
  // page (dev-server 500 loop, infinite JS on load, browser tab pinned) can
  // leave the whole runInteraction() promise pending forever. Cap at
  // 3× the per-action timeout so a normal 15s×3 interaction chain still
  // completes; anything past that is a real hang → mark as a fault and move
  // on so the batch keeps flowing.
  const HARD_CAP_MS = opts.timeoutMs * 3;
  const runOneWithCap = async (
    ctx: Parameters<typeof runInteraction>[0], it: Interaction,
  ): ReturnType<typeof runInteraction> => {
    return await Promise.race([
      runInteraction(ctx, it, opts),
      new Promise<Awaited<ReturnType<typeof runInteraction>>>((resolve) =>
        setTimeout(() => {
          const ev = emptyEvidence();
          ev.timed_out = true;
          ev.stack_trace = `HardTimeoutError: interaction ${it.id} did not complete within ${HARD_CAP_MS}ms`;
          resolve(ev);
        }, HARD_CAP_MS),
      ),
    ]);
  };

  const runGroup = async (route: string, items: Interaction[]) => {
    const { context, release } = await pool.acquire();
    try {
      for (const it of items) {
        let ev = await runOneWithCap(context, it);
        let isFlaky = false;
        if (!looksLikePass(it, ev)) {
          // Retry once
          const ev2 = await runOneWithCap(context, it);
          if (looksLikePass(it, ev2)) {
            isFlaky = true;
            ev = ev2;
          } else {
            ev = ev2;
          }
        }
        const passed_ = looksLikePass(it, ev);
        if (passed_) passed += 1;
        if (isFlaky) flaky += 1;
        faults.push({
          interaction_id: it.id,
          interaction: it,
          evidence: ev,
          passed: passed_,
          flaky: isFlaky,
        });
        progress?.onEvent("verify.progress", {
          run_id: runId,
          done: faults.length,
          total: req.interactions.length,
          current_route: route,
        });
      }
    } finally {
      await release();
    }
  };

  await Promise.all(
    Array.from(groups.entries()).map(([route, items]) => runGroup(route, items)),
  );

  const report: RunReport = {
    run_id: runId,
    project_id: req.project_id,
    target: req.target,
    base_url: opts.baseUrl,
    started_at: startedAt,
    finished_at: new Date().toISOString(),
    interactions_run: req.interactions.length,
    interactions_passed: passed,
    interactions_flaky: flaky,
    // Only failures land in the report — passes are counted, not enumerated.
    faults: faults.filter((f) => !f.passed),
  };

  progress?.onEvent("verify.done", {
    run_id: runId,
    faults_count: report.faults.length,
    passed, flaky,
  });
  return report;
}
