"use client";
import * as React from "react";
import { TokensProvider, defaultTokens } from "@tentoroforge/library";
import type { DesignSpec } from "./types";
import { NavFlowContext } from "./nav/NavFlowContext";

export interface EngineProviderProps {
  designSpec?: DesignSpec;
  navFlow?: any | null;     // NavFlowT shape; kept loose so generated apps don't
                             // pull the full schema types at type-check time
  /** Optional separate token tree (typically the project's tokens.custom.json)
   *  walked into CSS custom properties on the wrapper. Independent of
   *  designSpec.tokens, which is consumed by TokensProvider in its own
   *  expected shape. Pass this in the editor canvas so library components
   *  that read `var(--color-primary-500)` get the project's brand colors. */
  cssVarTokens?: Record<string, unknown> | null;
  /**
   * Emit the shadcn semantic colour vars (--background/--foreground/--primary…)
   * from the tokens. Values are RAW (hex) — correct for the render-scaffold,
   * whose Tailwind reads `var(--primary)` directly.
   *
   * GENERATED APPS must pass `false`: their Tailwind reads
   * `hsl(var(--primary))`, so a raw hex here yields `hsl(#2c8003)` — invalid,
   * silently dropped, text falls back to black (unreadable on dark themes).
   * Their `globals.css` already declares these vars in HSL-channel form from
   * the design pipeline, which is authoritative.
   */
  semanticVars?: boolean;
  children: React.ReactNode;
}

/**
 * React context that exposes the active DesignSpec to descendant Engine
 * components. Engine.tsx reads this to select the correct register-keyed
 * component variants (Hero.linear, Card.workday, etc.) via buildDefaultRegistry.
 */
export const DesignSpecContext = React.createContext<DesignSpec | null>(null);

/**
 * Walk a tokens tree (color.brand.primary, spacing.md, typography.body.family, ...)
 * and flatten it to CSS custom property declarations. Mirrors the convention
 * the generated globals.css uses so library components that read `var(--color-brand-primary)`
 * resolve against the project's tokens both in the standalone app and inside
 * the editor canvas.
 */
function tokensToCssVars(tokens: Record<string, unknown> | undefined): Record<string, string> {
  if (!tokens || typeof tokens !== "object") return {};
  const out: Record<string, string> = {};
  const walk = (obj: Record<string, unknown>, prefix: string) => {
    for (const [k, v] of Object.entries(obj)) {
      const key = `${prefix}-${k}`;
      if (v && typeof v === "object" && !Array.isArray(v)) {
        walk(v as Record<string, unknown>, key);
      } else if (typeof v === "string" || typeof v === "number") {
        out[`--${key}`] = String(v);
        // The component library consumes the SAME tokens under a `--token-`
        // prefix (library tokenVar() / renderer runtime compileTokens emit
        // `--token-spacing-4` style names). This emitter historically used
        // the bare prefix only, so every library-side var() deref resolved
        // to nothing — Cluster gaps computed to `normal` and toolbar
        // controls rendered fused together (live on cwx1stzz). Emit both.
        out[`--token-${key}`] = String(v);
      }
    }
  };
  for (const [category, sub] of Object.entries(tokens)) {
    if (sub && typeof sub === "object") {
      walk(sub as Record<string, unknown>, category);
    }
  }
  return out;
}

function getNested(obj: Record<string, unknown>, path: string[]): string | undefined {
  let cur: unknown = obj;
  for (const seg of path) {
    if (cur && typeof cur === "object" && !Array.isArray(cur) && seg in (cur as Record<string, unknown>)) {
      cur = (cur as Record<string, unknown>)[seg];
    } else return undefined;
  }
  return typeof cur === "string" ? cur : undefined;
}

/**
 * Convert a hex color to the shadcn-convention "H S% L%" components string
 * (e.g. "#10b981" → "158 64% 39%"), so a CSS rule like
 *   .bg-primary { background-color: hsl(var(--primary)); }
 * resolves to a valid color. Without this, `hsl(#10b981)` is invalid CSS
 * and the rule produces nothing — buttons render unstyled.
 *
 * Pass-throughs any non-hex string unchanged (already-HSL, named colors,
 * rgb() values, etc.) so callers using a different convention aren't broken.
 */
function hexToHslComponents(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const v = value.trim();
  if (!v.startsWith("#")) return v; // already non-hex — leave alone
  let hex = v.slice(1);
  if (hex.length === 3) hex = hex.split("").map(c => c + c).join("");
  if (hex.length !== 6) return v;
  const r = parseInt(hex.slice(0, 2), 16) / 255;
  const g = parseInt(hex.slice(2, 4), 16) / 255;
  const b = parseInt(hex.slice(4, 6), 16) / 255;
  if ([r, g, b].some(n => Number.isNaN(n))) return v;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  let h = 0;
  let s = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break;
      case g: h = (b - r) / d + 2; break;
      case b: h = (r - g) / d + 4; break;
    }
    h /= 6;
  }
  return `${Math.round(h * 360)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
}

/**
 * Map project tokens to shadcn-style semantic CSS variable names so that
 * library components using `bg-foreground`, `text-card-foreground`, etc.
 * pick up the project's brand colors within the EngineProvider wrapper.
 * Only vars with a resolved value are emitted; missing tokens fall back to
 * whatever `:root` declares (the editor's global defaults).
 */
export function tokensToSemanticVars(tokens: Record<string, unknown> | undefined): Record<string, string> {
  if (!tokens) return {};
  const c = (tokens.color ?? {}) as Record<string, unknown>;
  const pick = (...parts: string[]): string | undefined => getNested(c, parts);
  const map: Record<string, string | undefined> = {
    "--background":                 pick("surface", "0"),
    "--foreground":                 pick("primary", "900"),
    "--card":                       pick("surface", "1"),
    "--card-foreground":            pick("primary", "900"),
    "--popover":                    pick("surface", "1"),
    "--popover-foreground":         pick("primary", "900"),
    "--primary":                    pick("primary", "600"),
    "--primary-foreground":         pick("surface", "0"),
    "--secondary":                  pick("secondary", "100"),
    "--secondary-foreground":       pick("secondary", "900"),
    "--muted":                      pick("primary", "50"),
    "--muted-foreground":           pick("primary", "700"),
    "--accent":                     pick("accent", "100") ?? pick("accent", "500"),
    "--accent-foreground":          pick("accent", "900"),
    "--destructive":                pick("error", "500"),
    "--border":                     pick("primary", "100"),
    "--input":                      pick("primary", "100"),
    "--ring":                       pick("primary", "500"),
    "--sidebar":                    pick("surface", "1"),
    "--sidebar-foreground":         pick("primary", "900"),
    "--sidebar-primary":            pick("primary", "600"),
    "--sidebar-primary-foreground": pick("surface", "0"),
    "--sidebar-accent":             pick("primary", "50"),
    "--sidebar-accent-foreground":  pick("primary", "900"),
    "--sidebar-border":             pick("primary", "100"),
    "--sidebar-ring":               pick("primary", "500"),
    // Status semantic vars — used by status-aware components (Badge, Alert, etc.)
    // that need green/amber/info hues distinct from the brand primary.
    // Missing tokens silently skip (the `if (v)` guard below handles absent paths).
    "--success":                    pick("success", "500"),
    "--warning":                    pick("warning", "500"),
    "--info":                       pick("secondary", "500"),
  };
  const out: Record<string, string> = {};
  // Emit the raw token value (hex, oklch, etc.) so both editor and
  // render-scaffold can consume it directly via `var(--primary)`.
  // The scaffold's tailwind config is configured to use `var(--primary)`
  // not `hsl(var(--primary))` for the same reason — see
  // apps/render-scaffold/tailwind.config.ts comment about color tokens.
  for (const [k, v] of Object.entries(map)) {
    if (v) out[k] = v;
  }
  return out;
}

/**
 * Layout-level provider for the engine. Apply CSS variables from
 * design-spec, set the design register, provide nav-flow + tokens
 * to descendant pages.
 */
export function EngineProvider({ designSpec, navFlow, cssVarTokens, semanticVars: emitSemanticVars = true, children }: EngineProviderProps) {
  const register = (designSpec?.register as string) || "default";
  const baseTokens = (designSpec?.tokens as Record<string, Record<string, string>>) ?? defaultTokens;
  // Deep-merge the project's compiled tokens (tokens.custom.json) over the
  // base so the TokensProvider CONTEXT — not just the CSS variables — carries
  // the per-app identity. Previously only `radius` crossed over, so every
  // hook-reading component (useDensity/useElevation/useTokens().color.sidebar…)
  // rendered defaultTokens and all apps shared one personality.
  const custom = (cssVarTokens as Record<string, unknown> | null | undefined) ?? undefined;
  const tokens: Record<string, Record<string, string>> = React.useMemo(() => {
    if (!custom) return baseTokens;
    const out: Record<string, unknown> = { ...baseTokens };
    for (const [group, val] of Object.entries(custom)) {
      const base = (out as Record<string, unknown>)[group];
      out[group] =
        val && typeof val === "object" && base && typeof base === "object"
          ? { ...(base as object), ...(val as object) }
          : val;
    }
    return out as Record<string, Record<string, string>>;
  }, [custom, baseTokens]);
  // Walk cssVarTokens (project's tokens.custom.json) if provided; otherwise
  // fall back to walking designSpec.tokens so older callers still get something.
  const cssVars = React.useMemo(
    () => tokensToCssVars((cssVarTokens as Record<string, unknown>) ?? tokens),
    [cssVarTokens, tokens]
  );
  const semanticVars = React.useMemo(
    () => (emitSemanticVars
      ? tokensToSemanticVars((cssVarTokens as Record<string, unknown>) ?? tokens)
      : {}),
    [emitSemanticVars, cssVarTokens, tokens]
  );
  const mergedStyle = { ...cssVars, ...semanticVars };

  return (
    <DesignSpecContext.Provider value={designSpec ?? null}>
      <div
        data-tentoro-engine=""
        data-register={register}
        style={mergedStyle as React.CSSProperties}
      >
        <NavFlowContext.Provider value={navFlow ?? null}>
          <TokensProvider register={register as any} tokens={tokens as any}>
            {children}
          </TokensProvider>
        </NavFlowContext.Provider>
      </div>
    </DesignSpecContext.Provider>
  );
}
