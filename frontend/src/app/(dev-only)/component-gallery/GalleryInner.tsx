"use client";

import * as React from "react";
import { Engine, EngineProvider } from "@tentoroforge/engine";
import { starterRegistry } from "@forge/registry";

/**
 * EVERY registry component, rendered through the REAL Engine, twice.
 *
 * `?variant=plain` renders each component with only its registry defaults.
 * `?variant=styled` renders the identical tree with a StyleSlot applied.
 * Screenshotting both and pixel-diffing them answers a question the store-level
 * sweep cannot: did the style have any VISUAL effect at all? A zero diff means
 * the control did nothing the user can see — regardless of whether the value
 * reached the artifact, which is all Tier 1 could prove.
 *
 * THE TOKENS BELOW ARE LOAD-BEARING, NOT DECORATION. applyStyleSlot emits
 * `var(--token-spacing-8)` and friends; with no token values in scope those vars
 * resolve to nothing, both variants render identically, and the sweep would
 * report all 133 components as "style has no visual effect" — 133 false
 * findings from an empty theme. Concrete values are supplied so a var that
 * resolves produces a visible difference.
 */
const TOKENS: Record<string, any> = {
  color: {
    surface: { "0": "#ffffff", "1": "#e8f0fe", "2": "#dbe7fb" },
    primary: { "50": "#eef2ff", "500": "#3b82f6", "600": "#2563eb", "900": "#1e3a8a" },
    secondary: { "500": "#8b5cf6" },
  },
  spacing: { "2": "8px", "4": "16px", "8": "48px" },
  radius: { sm: "4px", md: "10px", lg: "28px" },
  shadow: { sm: "0 1px 2px rgba(0,0,0,.2)", md: "0 4px 10px rgba(0,0,0,.3)", lg: "0 12px 32px rgba(0,0,0,.45)" },
  motion: { fast: "120ms", slow: "400ms" },
  typography: { fontFamily: { base: "Inter" }, scale: { body: 14 } },
  breakpoints: {},
};

/** The StyleSlot applied in the `styled` variant — one value per visual key. */
const STYLED = {
  padding: "spacing.8",
  radius: "radius.lg",
  shadow: "shadow.lg",
  background: "color.surface.2",
};

const NAV_FLOW = {
  version: "1.0",
  initialPage: "home",
  pages: [{ id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] }],
  transitions: [],
  guards: {},
};

function defaultProps(entry: any): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, d] of Object.entries(entry.props ?? {}) as Array<[string, any]>) {
    if (d?.default !== undefined) out[name] = d.default;
  }
  return out;
}

export default function GalleryInner({ variant }: { variant: "plain" | "styled" }) {
  const names = React.useMemo(() => Object.keys(starterRegistry).sort(), []);

  return (
    <main style={{ background: "#f6f7f9", padding: 16 }}>
      <h1 style={{ fontSize: 14, marginBottom: 12 }}>
        Component gallery — {names.length} components — variant: {variant}
      </h1>
      {names.map((name) => {
        const entry = (starterRegistry as any)[name];
        const node: any = {
          id: `n-${name}`,
          type: name,
          props: defaultProps(entry),
          children: entry?.slots?.type === "leaf" ? undefined : [],
        };
        if (variant === "styled") node.style = STYLED;

        const page = {
          schemaVersion: "2",
          id: "home",
          route: "/",
          root: { id: "root", type: "Container", props: {}, children: [node] },
        };

        return (
          <section
            key={name}
            data-component={name}
            // A FIXED BOX per component. Without it one component's height change
            // reflows every component below it, so a single real difference would
            // register as 133 differences and the diff would mean nothing.
            style={{
              width: 520, height: 260, overflow: "hidden", background: "#fff",
              border: "1px solid #d8dce2", borderRadius: 6, margin: "0 0 14px 0",
              display: "inline-block", verticalAlign: "top", marginRight: 14,
            }}
          >
            <div style={{ fontSize: 10, padding: "3px 6px", background: "#eef1f5", color: "#444" }}>
              {name}
            </div>
            <div style={{ padding: 8, height: 232, overflow: "hidden" }}>
              <ErrorBoundary name={name}>
                <EngineProvider designSpec={{}} navFlow={NAV_FLOW as any} cssVarTokens={TOKENS}>
                  <Engine schema={page as any} previewData={{}} />
                </EngineProvider>
              </ErrorBoundary>
            </div>
          </section>
        );
      })}
    </main>
  );
}

/**
 * One component throwing must not blank the whole gallery — the sweep needs the
 * other 132 to still render, and "this one threw" is itself a finding worth
 * recording rather than an aborted page.
 */
class ErrorBoundary extends React.Component<
  { name: string; children: React.ReactNode },
  { err: string | null }
> {
  constructor(p: any) { super(p); this.state = { err: null }; }
  static getDerivedStateFromError(e: any) { return { err: String(e?.message ?? e).slice(0, 120) }; }
  render() {
    if (this.state.err) {
      return (
        <div data-gallery-threw={this.props.name} style={{ color: "#b00", fontSize: 10 }}>
          threw: {this.state.err}
        </div>
      );
    }
    return this.props.children as any;
  }
}
