"use client";

/**
 * React context for active tokens. Components read the active values via
 * useTokens() rather than re-parsing CSS variables, so derived values
 * (e.g. density-aware gap pixels) can be computed once per render.
 *
 * The provider is optional — components fall back to defaultTokens when
 * unwrapped. This keeps the existing schema-driven runtime working without
 * the editor or scaffold needing to install the provider.
 *
 * Wave 2 convenience hooks:
 *   useDensity()       → "compact" | "comfortable" | "spacious"
 *   useElevation()     → "flat" | "bordered" | "layered" | "floating"
 *   useMotionLevel()   → "none" | "subtle" | "expressive"
 *   useRadiusScale()   → "sharp" | "soft" | "round"
 *
 * NOTE: `useMotionLevel` reads `tokens.motionLevel` (the Wave 2 intensity scalar),
 * NOT `tokens.motion` (the animation duration/easing config object).
 */

import * as React from "react";
import { defaultTokens } from "./default-tokens";
import type { Density, Elevation, Motion, RadiusScale } from "./token-types";
import { resolveTokens, type RegisterName } from "./registers";

type TokenSnapshot = typeof defaultTokens;

const TokensContext = React.createContext<TokenSnapshot>(defaultTokens);

export function TokensProvider({
  tokens,
  register,
  children,
}: {
  tokens?: Partial<TokenSnapshot>;
  register?: RegisterName;
  children: React.ReactNode;
}) {
  const merged = React.useMemo(() => {
    const base = resolveTokens(register); // start from register bundle (or defaults if no register)
    if (!tokens) return base;
    // Merge ad-hoc overrides on top of register
    return { ...base, ...tokens } as TokenSnapshot;
  }, [tokens, register]);
  return <TokensContext.Provider value={merged}>{children}</TokensContext.Provider>;
}

export function useTokens(): TokenSnapshot {
  return React.useContext(TokensContext);
}

/** Density: drives default gaps and paddings across layout components. */
export function useDensity(): Density {
  return useTokens().density as Density;
}

/** Elevation: drives shadow/border treatment on card-like surfaces. */
export function useElevation(): Elevation {
  return useTokens().elevation as Elevation;
}

/**
 * Motion intensity level (Wave 2).
 * Reads `tokens.motionLevel` — distinct from `tokens.motion.duration/easing`.
 */
export function useMotionLevel(): Motion {
  return useTokens().motionLevel as Motion;
}

/** Radius scale: drives corner radius family across interactive components. */
export function useRadiusScale(): RadiusScale {
  return useTokens().radius.scale as RadiusScale;
}
