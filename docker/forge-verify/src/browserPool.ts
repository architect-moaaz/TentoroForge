/**
 * Warm Chromium browser pool.
 *
 * Cold browser launch is ~800ms; incognito-context creation off a warm
 * browser is ~20ms. We keep ONE headless browser and vend fresh incognito
 * contexts per run so cookies/localStorage don't bleed across runs.
 *
 * Concurrency bound: `maxContexts` cap keeps memory sane. Callers await
 * `acquire()` which blocks when the pool is full, releases back on
 * `context.close()` via the returned closer.
 */
import { Browser, BrowserContext, chromium } from "playwright";

export interface PoolConfig {
  maxContexts: number;
}

class Semaphore {
  private permits: number;
  private waiters: Array<() => void> = [];
  constructor(n: number) { this.permits = n; }
  async acquire(): Promise<() => void> {
    if (this.permits > 0) { this.permits -= 1; return () => this.release(); }
    await new Promise<void>((resolve) => this.waiters.push(resolve));
    this.permits -= 1;
    return () => this.release();
  }
  private release(): void {
    this.permits += 1;
    const next = this.waiters.shift();
    if (next) next();
  }
}

export class BrowserPool {
  private browser: Browser | null = null;
  private sem: Semaphore;
  constructor(private cfg: PoolConfig) {
    this.sem = new Semaphore(cfg.maxContexts);
  }

  async warm(): Promise<void> {
    if (this.browser) return;
    this.browser = await chromium.launch({
      headless: true,
      // --no-sandbox is required to run Chromium inside a Docker container
      // (playwright image ships with the seccomp profile but we still need
      // this for the child renderer processes).
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
  }

  /** Acquire a fresh incognito context. Caller MUST close it. */
  async acquire(): Promise<{ context: BrowserContext; release: () => Promise<void> }> {
    await this.warm();
    const releaseSem = await this.sem.acquire();
    const context = await this.browser!.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1440, height: 900 },
    });
    const release = async () => {
      try { await context.close(); } catch { /* already closed */ }
      releaseSem();
    };
    return { context, release };
  }

  async close(): Promise<void> {
    if (this.browser) {
      await this.browser.close();
      this.browser = null;
    }
  }
}
