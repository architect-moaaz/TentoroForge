import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * FilterBuilder — Spec E Wave 3 chip-based filter expression builder.
 *
 * Emits a query state serialisable to a URL search param. Deliberately
 * flat for the first cut: a list of `{field, operator, value}` clauses
 * combined by a single top-level `AND` / `OR`. Nested groups can land
 * later; the schema leaves room by keeping the top-level `combinator`
 * a discriminated enum.
 */
const FilterField = z
  .object({
    name: z.string().min(1),
    label: z.string().optional(),
    type: z
      .enum(["string", "number", "boolean", "date", "enum"])
      .default("string"),
    /** Optional restricted operator list; falls back to type defaults. */
    operators: z.array(z.string()).optional(),
    /** For type="enum" — allowed values (label/value pairs). */
    options: z
      .array(z.object({ value: z.string(), label: z.string() }))
      .optional(),
  })
  .strict();

export const FilterBuilderProps = z
  .object({
    fields: z.array(FilterField).min(1),
    /** URL query param the serialised expression is stored under. */
    paramKey: z.string().default("filter"),
    /** Top-level combinator: AND (default) or OR. */
    combinator: z.enum(["AND", "OR"]).default("AND"),
    /** Placeholder shown when there are no clauses yet. */
    emptyLabel: z.string().optional(),
    /** Workflow name to dispatch with the compiled query on Apply. */
    onApplyWorkflow: z.string().optional(),
    style: StyleSlot.optional(),
    className: z.string().optional(),
  })
  .strict();

export type FilterBuilderPropsType = z.infer<typeof FilterBuilderProps>;
export type FilterFieldType = z.infer<typeof FilterField>;
