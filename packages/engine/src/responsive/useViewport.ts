"use client";
import * as React from "react";

export type Breakpoint = "default" | "sm" | "md" | "lg" | "xl";

const BREAKPOINTS: Array<[Breakpoint, number]> = [
  ["xl", 1280],
  ["lg", 1024],
  ["md", 768],
  ["sm", 480],
  ["default", 0],
];

const RESP_KEYS = new Set<Breakpoint>(["default", "sm", "md", "lg", "xl"]);

export function useViewport(): Breakpoint {
  const [bp, setBp] = React.useState<Breakpoint>(() => {
    if (typeof window === "undefined") return "default";
    return bpForWidth(window.innerWidth);
  });
  React.useEffect(() => {
    const update = () => setBp(bpForWidth(window.innerWidth));
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return bp;
}

function bpForWidth(w: number): Breakpoint {
  for (const [name, min] of BREAKPOINTS) {
    if (w >= min) return name;
  }
  return "default";
}

/**
 * Given a prop value that MAY be `{ default, sm, md, lg, xl }` shape,
 * pick the value for the active breakpoint. Falls back: xl → lg → md →
 * sm → default. Plain literals (string, number, array, non-bp object)
 * pass through.
 */
export function pickResponsiveValue<T>(value: T | Record<Breakpoint, T>, bp: Breakpoint): T {
  if (value === null || value === undefined) return value;
  if (typeof value !== "object" || Array.isArray(value)) return value as T;

  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj);
  if (keys.length === 0) return value as T;

  // Must contain ONLY breakpoint keys to be considered a responsive shape.
  // This guards against false positives like { url, overlay } on Hero.backgroundImage.
  if (!keys.every(k => RESP_KEYS.has(k as Breakpoint))) return value as T;

  const order: Breakpoint[] = ["xl", "lg", "md", "sm", "default"];
  const startIdx = order.indexOf(bp);
  for (let i = startIdx; i < order.length; i++) {
    if (obj[order[i]] !== undefined) return obj[order[i]] as T;
  }
  return value as T;
}
