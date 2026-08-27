// packages/library/src/theme/registers/index.ts
import type { RegisterBundle, RegisterName } from "./types";
import { defaultTokens } from "../default-tokens";
import { workdayRegister } from "./workday";
import { linearRegister } from "./linear";
import { stripeRegister } from "./stripe";
import { notionRegister } from "./notion";
import { figmaRegister } from "./figma";

const REGISTRY: Partial<Record<RegisterName, RegisterBundle>> = {
  workday: workdayRegister,
  linear:  linearRegister,
  stripe:  stripeRegister,
  notion:  notionRegister,
  figma:   figmaRegister,
};

/**
 * Return the bundle for a register name, or null for "default" / unknown.
 * Callers merge the bundle's tokens into defaultTokens to get the active set.
 */
export function getRegister(name: RegisterName | undefined): RegisterBundle | null {
  if (!name || name === "default") return null;
  return REGISTRY[name] ?? null;
}

/**
 * Deep-merge a register bundle's overrides on top of defaultTokens.
 * Returns a fresh token snapshot ready to feed into TokensProvider.
 */
export function resolveTokens(name: RegisterName | undefined): typeof defaultTokens {
  const bundle = getRegister(name);
  if (!bundle) return defaultTokens;
  return deepMerge(defaultTokens, bundle.tokens) as typeof defaultTokens;
}

function deepMerge<A extends object, B extends object>(a: A, b: B): A {
  const out: any = { ...a };
  for (const [k, v] of Object.entries(b)) {
    if (v !== null && typeof v === "object" && !Array.isArray(v) &&
        out[k] !== null && typeof out[k] === "object" && !Array.isArray(out[k])) {
      out[k] = deepMerge(out[k], v as any);
    } else {
      out[k] = v;
    }
  }
  return out;
}

export type { RegisterBundle, RegisterName };
export { workdayRegister } from "./workday";
export { linearRegister } from "./linear";
export { stripeRegister } from "./stripe";
export { notionRegister } from "./notion";
export { figmaRegister } from "./figma";
