/**
 * Living Application Blueprint — public surface.
 *
 * PRD §9–25. The Blueprint is the canonical representation of what an
 * application *is* (§9), and per §115 sits between approved user intent and
 * the generated implementation.
 *
 * Authored once here in Zod; :func:`blueprintJsonSchema` emits the JSON Schema
 * that the Python side validates against, so both halves of the platform share
 * one definition rather than two that drift.
 */
export * from "./ids";
export * from "./blueprint";

import { zodToJsonSchema } from "zod-to-json-schema";
import { Blueprint } from "./blueprint";

/**
 * `zodToJsonSchema`'s generic exceeds TypeScript's type-instantiation depth on
 * a schema this large (TS2589) — `pageJsonSchema()` does not hit it because
 * `Page` is smaller. Runtime conversion is unaffected, so widen the signature
 * at this one boundary rather than degrading the Blueprint's own types.
 */
const toJsonSchema = zodToJsonSchema as (
  schema: unknown,
  options?: unknown,
) => Record<string, unknown>;

/** JSON Schema (draft-07) for the Living Blueprint — the cross-language contract. */
export function blueprintJsonSchema(): Record<string, unknown> {
  return toJsonSchema(Blueprint, { target: "jsonSchema7" });
}
