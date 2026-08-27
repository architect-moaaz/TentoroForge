"use client";

/**
 * SchemaPageBoundary — catches any render-time error thrown inside the
 * schema-driven page (Engine + its children) so one crashing component
 * or one bad binding never blanks the whole page.
 *
 * Why this exists: SSR of a schema page can throw for reasons the
 * generation pipeline can't always eliminate — an LLM-emitted component
 * that reads an undefined token subtree, a binding that dereferences a
 * missing dataSource row, a library component with a runtime assumption
 * that a design brief violated. Without this, Next 15's default RSC
 * error handling replaces the whole route with "Application error"
 * plus an opaque digest, which is what testers see today
 * (bug B-020.8 class).
 *
 * The boundary logs the digest server-side so operators can trace
 * back to the actual stack in Vercel logs, then renders a small
 * in-place error card so the rest of the app still navigates.
 *
 * NOTE: this is a CLIENT component. React error boundaries can't be
 * server components — that's a React constraint, not ours. schema-page
 * is server-rendered but the boundary catches errors thrown during
 * hydration and client renders. For SSR-only crashes Next automatically
 * routes to the nearest error.tsx; we ship one in app/(dashboard)/
 * as a companion in the same commit.
 */

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Route the boundary is protecting — surfaced in the fallback so users
   *  can screenshot something specific and testers can filter logs. */
  route?: string;
}

interface State {
  error: Error | null;
}

export class SchemaPageBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    // Console log survives to server logs when this fires during SSR
    // hydration mismatch. Include the digest React attaches so it can
    // be matched to Vercel's own error listing.
    // eslint-disable-next-line no-console
    console.error(
      `[schema-page-boundary] route=${this.props.route ?? "?"} caught render error:\n`,
      error?.stack || error?.message || error,
      info?.componentStack ? `\ncomponent stack:${info.componentStack}` : "",
    );
  }

  render() {
    if (!this.state.error) return this.props.children;
    const { error } = this.state;
    const digest = (error as unknown as { digest?: string }).digest;
    return (
      <div
        role="alert"
        className="mx-auto my-8 max-w-2xl rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-900 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-200"
      >
        <div className="mb-2 text-base font-semibold">
          Something went wrong rendering this page.
        </div>
        <div className="mb-3 opacity-80">
          The rest of the app should still work — try navigating elsewhere and
          returning, or refresh the page. If this keeps happening, share the
          route and error id below.
        </div>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 font-mono text-xs opacity-70">
          {this.props.route && (
            <>
              <dt>route</dt>
              <dd>{this.props.route}</dd>
            </>
          )}
          {digest && (
            <>
              <dt>error id</dt>
              <dd>{digest}</dd>
            </>
          )}
          <dt>message</dt>
          <dd className="break-words">{error.message || "unknown"}</dd>
        </dl>
      </div>
    );
  }
}
