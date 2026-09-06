/**
 * Per-Interaction runners.
 *
 * One function per Interaction kind. Each is handed a fresh BrowserContext
 * + Interaction + base URL, drives one action, and returns Evidence. All
 * assertions are triangulated (network + DOM + console) — the Python-side
 * classifier decides what's a fault; runners only OBSERVE.
 */
import { BrowserContext, Page, Response } from "playwright";
import {
  classifyRenderTruth,
  emptyWidgetCounts,
  type WidgetCounts,
} from "./renderTruth.js";
import {
  ButtonInteraction,
  DetailInteraction,
  Evidence,
  FormInteraction,
  Interaction,
  ListInteraction,
  LogEntry,
  NetworkEntry,
  RouteInteraction,
  emptyEvidence,
} from "./types.js";

const DEFAULT_TIMEOUT_MS = 15_000;

interface RunOpts {
  baseUrl: string;
  timeoutMs?: number;
  auth?: { username: string; password: string; login_route?: string };
}

// ── Common instrumentation ──────────────────────────────────────────────


/** Attach network + console listeners; return callable that returns the log. */
function instrument(page: Page): {
  net: NetworkEntry[];
  logs: LogEntry[];
  detach: () => void;
} {
  const net: NetworkEntry[] = [];
  const logs: LogEntry[] = [];

  const onResp = (resp: Response) => {
    try {
      const req = resp.request();
      net.push({ method: req.method(), url: resp.url(), status: resp.status() });
    } catch { /* response race — ignore */ }
  };
  const onConsole = (msg: any) => {
    logs.push({ level: msg.type() as LogEntry["level"], text: msg.text() });
  };
  const onPageError = (err: Error) => {
    logs.push({ level: "error", text: err.message + "\n" + (err.stack || "") });
  };

  page.on("response", onResp);
  page.on("console", onConsole);
  page.on("pageerror", onPageError);

  const detach = () => {
    page.off("response", onResp);
    page.off("console", onConsole);
    page.off("pageerror", onPageError);
  };
  return { net, logs, detach };
}


async function login(page: Page, opts: RunOpts): Promise<void> {
  if (!opts.auth) return;
  const loginRoute = opts.auth.login_route || "/login";
  await page.goto(opts.baseUrl + loginRoute, { waitUntil: "networkidle" });
  // Best-effort form fill — many templates use name="email" + name="password".
  await page.fill('input[name="email"], input[type="email"]', opts.auth.username).catch(() => {});
  await page.fill('input[name="password"], input[type="password"]', opts.auth.password).catch(() => {});
  await Promise.all([
    page.waitForLoadState("networkidle"),
    page.click('button[type="submit"]').catch(() => page.click("button:has-text('Sign in')")),
  ]).catch(() => {});
}


function bodyExcerpt(body: string | null | undefined): string | null {
  if (!body) return null;
  return body.slice(0, 2048);
}


function extractStackFromBody(body: string): string | null {
  // Next.js dev-mode error pages have a <script> with the stack;
  // production shows a generic error. In both cases the body contains
  // useful text about ENOENT / postgres etc — good enough for the
  // classifier's regex-based signature detection.
  const errIdx = body.toLowerCase().indexOf("error");
  if (errIdx < 0) return null;
  return body.slice(errIdx, Math.min(body.length, errIdx + 2048));
}

// ── Route runner ────────────────────────────────────────────────────────


export async function runRoute(
  context: BrowserContext, i: RouteInteraction, opts: RunOpts,
): Promise<Evidence> {
  const timeoutMs = opts.timeoutMs || DEFAULT_TIMEOUT_MS;
  const page = await context.newPage();
  const { net, logs, detach } = instrument(page);
  const ev = emptyEvidence();
  try {
    if (i.requires_auth) await login(page, opts);
    const url = opts.baseUrl + i.route.replace(/\[([^\]]+)\]/g, "smoke");
    const resp = await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
    ev.status = resp?.status() ?? null;
    if (ev.status && ev.status >= 400) {
      const body = await resp!.text().catch(() => "");
      ev.body_excerpt = bodyExcerpt(body);
      ev.stack_trace = extractStackFromBody(body);
    }
    ev.url_after_click = page.url();
    ev.rendered_widget_count = await countWidgets(page);
    ev.render_truth = classifyRenderTruth(await probeRenderTruth(page));
  } catch (err: any) {
    if ((err.message || "").includes("Timeout")) {
      ev.timed_out = true;
    } else {
      ev.stack_trace = err.message;
    }
  } finally {
    ev.console = logs;
    ev.network_log = net;
    detach();
    await page.close();
  }
  return ev;
}


/**
 * Count what each data-bound widget actually DREW, not merely that it exists.
 *
 * Runs entirely in the page so it sees post-hydration reality — the recharts
 * failure is invisible to any check that reads the schema or the server HTML,
 * because the <g> wrapper is present and only the <path> inside is missing.
 */
async function probeRenderTruth(page: Page): Promise<WidgetCounts> {
  try {
    return await page.evaluate(() => {
      const n = (sel: string) => document.querySelectorAll(sel).length;
      // Every recharts mark type: bars, line vertices, area fills, pie
      // sectors, radar polygons. A chart that drew ANY of these is alive.
      const marks = n(
        ".recharts-rectangle, .recharts-line-curve, .recharts-area-area, " +
        ".recharts-sector, .recharts-radar-polygon, .recharts-dot",
      );
      // MetricTile already stamps data-metric-tile / data-metric-value —
      // use the contract that exists rather than minting a parallel one.
      const metricEls = Array.from(document.querySelectorAll("[data-metric-tile]"));
      const blank = metricEls.filter((el) => {
        const v = el.querySelector("[data-metric-value]");
        // No value slot at all, or one holding nothing but whitespace.
        // NOTE "—" is NOT blank: MetricTile renders it deliberately to
        // distinguish "no data yet" from "the value is zero", so counting it
        // as a fault would punish the component for being honest.
        return !v || !(v.textContent || "").trim();
      }).length;
      return {
        charts: n(".recharts-wrapper"),
        chartMarks: marks,
        chartsEmptyState: n('[data-forge-empty="chart"]'),
        tables: n("table"),
        tableRows: n("table tbody tr:not([data-forge-empty])"),
        tablesEmptyState: n('[data-forge-empty="table"]'),
        metrics: metricEls.length,
        metricsBlank: blank,
      };
    });
  } catch {
    // A probe that cannot run must not invent a verdict. Zeroed counts read
    // as "no widgets", which produces no findings — silence, not a false pass
    // on a page that does have widgets.
    return emptyWidgetCounts();
  }
}


async function countWidgets(page: Page): Promise<number> {
  // Structural proxy for "how much stuff is on this page". Cards, tables,
  // stats, charts. Cheap DOM query — no XPath.
  try {
    return await page.locator(
      '[data-forge-widget], [role="region"], table, .card, [data-slot="stat"]',
    ).count();
  } catch {
    return 0;
  }
}

// ── Button runner ───────────────────────────────────────────────────────


export async function runButton(
  context: BrowserContext, i: ButtonInteraction, opts: RunOpts,
): Promise<Evidence> {
  const timeoutMs = opts.timeoutMs || DEFAULT_TIMEOUT_MS;
  const page = await context.newPage();
  const { net, logs, detach } = instrument(page);
  const ev = emptyEvidence();
  try {
    if (opts.auth) await login(page, opts);
    // Land on the button's page
    await page.goto(opts.baseUrl + i.route.replace(/\[([^\]]+)\]/g, "smoke"), {
      waitUntil: "domcontentloaded", timeout: timeoutMs,
    });
    // Find the button — prefer the extractor's selector, fall back to text.
    const btn = i.selector.startsWith("role=")
      ? page.getByRole("button", { name: i.label })
      : page.locator(i.selector);
    // BUTTON_NO_ACTION_DECLARED — Python classifier handles this via
    // the interaction shape alone; we still record what happened.
    const beforeUrl = page.url();
    await btn.first().click({ timeout: timeoutMs }).catch((e) => {
      ev.stack_trace = "click failed: " + e.message;
    });
    // Give the app a beat to fire network / navigate
    await page.waitForLoadState("networkidle", { timeout: 2000 }).catch(() => {});
    ev.url_after_click = page.url();
    if (i.action.kind === "navigate" && ev.url_after_click !== beforeUrl) {
      // Follow-through: what did the target return?
      const targetResp = await page.goto(page.url(), {
        waitUntil: "domcontentloaded", timeout: timeoutMs,
      }).catch(() => null);
      if (targetResp) ev.status = targetResp.status();
    }
    ev.dom_snapshot = await btn.first().evaluate((el: any) => el.outerHTML)
      .catch(() => null);
  } catch (err: any) {
    if ((err.message || "").includes("Timeout")) ev.timed_out = true;
    else ev.stack_trace = err.message;
  } finally {
    ev.console = logs;
    ev.network_log = net;
    detach();
    await page.close();
  }
  return ev;
}

// ── Form runner ─────────────────────────────────────────────────────────


function synthValue(field: { name: string; type: string; options?: string[] }): string {
  if (field.options && field.options.length) return field.options[0];
  switch (field.type) {
    case "email": return `t-${Date.now()}@forge.test`;
    case "uuid":  return "00000000-0000-4000-8000-000000000000";
    case "number":
    case "integer": return "1";
    case "date":  return "2026-01-01";
    case "timestamp": return "2026-01-01T00:00:00Z";
    case "boolean": return "true";
    case "file":  return ""; // handled separately; skip fill
    default:      return "smoke-" + field.name;
  }
}


export async function runForm(
  context: BrowserContext, i: FormInteraction, opts: RunOpts,
): Promise<Evidence> {
  const timeoutMs = opts.timeoutMs || DEFAULT_TIMEOUT_MS;
  const page = await context.newPage();
  const { net, logs, detach } = instrument(page);
  const ev = emptyEvidence();
  try {
    if (opts.auth) await login(page, opts);
    await page.goto(opts.baseUrl + i.route.replace(/\[([^\]]+)\]/g, "smoke"), {
      waitUntil: "domcontentloaded", timeout: timeoutMs,
    });
    // Fill fields
    for (const f of i.fields) {
      if (f.type === "file") continue;
      const val = synthValue(f);
      await page.fill(`[name="${f.name}"]`, val).catch(async () => {
        // Some Selects don't accept fill; try selectOption instead.
        await page.selectOption(`[name="${f.name}"]`, val).catch(() => {});
      });
    }
    // Submit — prefer the extractor's selector, fall back to button[type=submit].
    await Promise.all([
      page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {}),
      page.click('button[type="submit"]').catch(() => page.click("button:has-text('Save'), button:has-text('Create'), button:has-text('Submit')")),
    ]);
    // Look for the primary POST in the network log
    const posts = net.filter((n) => n.method === "POST");
    if (posts.length) ev.status = posts[posts.length - 1].status;
  } catch (err: any) {
    if ((err.message || "").includes("Timeout")) ev.timed_out = true;
    else ev.stack_trace = err.message;
  } finally {
    ev.console = logs;
    ev.network_log = net;
    detach();
    await page.close();
  }
  return ev;
}

// ── List runner ─────────────────────────────────────────────────────────


export async function runList(
  context: BrowserContext, i: ListInteraction, opts: RunOpts,
): Promise<Evidence> {
  const timeoutMs = opts.timeoutMs || DEFAULT_TIMEOUT_MS;
  const page = await context.newPage();
  const { net, logs, detach } = instrument(page);
  const ev = emptyEvidence();
  try {
    if (opts.auth) await login(page, opts);
    // Hit the API directly — that's where LIST_EMPTY and LIST_DATASOURCE_UNRESOLVED show up.
    const url = `${opts.baseUrl}/api/data/${i.dataSource}?limit=25`;
    const resp = await page.request.get(url, { timeout: timeoutMs }).catch(() => null);
    if (!resp) {
      ev.timed_out = true;
    } else {
      ev.status = resp.status();
      const text = await resp.text().catch(() => "");
      ev.body_excerpt = bodyExcerpt(text);
      if (ev.status === 200) {
        try {
          const j = JSON.parse(text);
          const rows = j.rows ?? j.data ?? j;
          ev.rows_returned = Array.isArray(rows) ? rows.length : null;
        } catch { /* leave rows_returned null */ }
      }
    }
  } catch (err: any) {
    ev.stack_trace = err.message;
  } finally {
    ev.console = logs;
    ev.network_log = net;
    detach();
    await page.close();
  }
  return ev;
}

// ── Detail runner ───────────────────────────────────────────────────────


export async function runDetail(
  context: BrowserContext, i: DetailInteraction, opts: RunOpts,
): Promise<Evidence> {
  const timeoutMs = opts.timeoutMs || DEFAULT_TIMEOUT_MS;
  const page = await context.newPage();
  const { net, logs, detach } = instrument(page);
  const ev = emptyEvidence();
  try {
    if (opts.auth) await login(page, opts);
    // Pluck a real id from the entity's API if we can
    let seedId = "smoke";
    if (i.entity) {
      const listUrl = `${opts.baseUrl}/api/data/${i.entity.toLowerCase()}s?limit=1`;
      const listResp = await page.request.get(listUrl, { timeout: 5000 }).catch(() => null);
      if (listResp && listResp.ok()) {
        const j = await listResp.json().catch(() => ({}));
        const rows = j.rows ?? j.data ?? [];
        if (Array.isArray(rows) && rows[0]?.id) seedId = rows[0].id;
      }
    }
    const url = opts.baseUrl + i.route.replace(/\[[^\]]+\]/, seedId);
    const resp = await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
    ev.status = resp?.status() ?? null;
    if (ev.status && ev.status >= 400) {
      ev.body_excerpt = bodyExcerpt(await resp!.text().catch(() => ""));
    }
    // DOM snapshot to spot unresolved {{bindings}}
    ev.dom_snapshot = await page.locator("main, body").innerHTML().catch(() => null);
    if (ev.dom_snapshot) ev.dom_snapshot = ev.dom_snapshot.slice(0, 4096);
  } catch (err: any) {
    if ((err.message || "").includes("Timeout")) ev.timed_out = true;
    else ev.stack_trace = err.message;
  } finally {
    ev.console = logs;
    ev.network_log = net;
    detach();
    await page.close();
  }
  return ev;
}

// ── Dispatcher ──────────────────────────────────────────────────────────


export async function runInteraction(
  context: BrowserContext, i: Interaction, opts: RunOpts,
): Promise<Evidence> {
  switch (i.kind) {
    case "route":  return runRoute(context, i, opts);
    case "button": return runButton(context, i, opts);
    case "form":   return runForm(context, i, opts);
    case "list":   return runList(context, i, opts);
    case "detail": return runDetail(context, i, opts);
  }
}
