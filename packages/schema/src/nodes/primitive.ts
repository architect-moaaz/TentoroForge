import { z } from "zod";
import { StyleProps } from "../tokens";
import { Expression, EventHandler, EventName, DataBinding } from "../expressions";
import { Node } from "./index";

// Forward-declared Node ref — ESM circular import is safe with z.lazy because
// Zod defers resolution until parse time, by which point nodes/index.ts is
// fully loaded.
const NodeRef: z.ZodTypeAny = z.lazy(() => Node);

const Envelope = {
  id: z.string().min(1),
  style: StyleProps.optional(),
  bind: DataBinding.optional(),
  visibleIf: Expression.optional(),
  on: z.record(EventName, EventHandler).optional(),
};

export const BoxNode = z
  .object({
    ...Envelope,
    type: z.literal("Box"),
    props: z
      .object({
        as: z.enum(["div", "section", "article", "aside", "header", "footer", "main", "nav"])
          .default("div"),
      })
      .strict()
      .optional(),
    children: z.array(NodeRef).default([]),
  })
  .strict();

export const TextNode = z
  .object({
    ...Envelope,
    type: z.literal("Text"),
    props: z
      .object({
        content: z.string().optional(),
        as: z
          .enum(["span", "p", "h1", "h2", "h3", "h4", "h5", "h6", "label", "strong", "em"])
          .default("span"),
      })
      .strict()
      .optional(),
  })
  .strict()
  .refine((v) => v.props?.content !== undefined || v.bind !== undefined, {
    message: "Text requires either props.content or bind",
  });

export const ImageNode = z
  .object({
    ...Envelope,
    type: z.literal("Image"),
    props: z
      .object({
        src: z.string().min(1),
        alt: z.string(),
        width: z.number().int().positive().optional(),
        height: z.number().int().positive().optional(),
      })
      .strict(),
  })
  .strict();

// z.union rather than z.discriminatedUnion because TextNode uses .refine(),
// which produces ZodEffects — incompatible with discriminatedUnion in Zod 3.
export const PrimitiveNode = z.union([BoxNode, TextNode, ImageNode]);
export type PrimitiveNode = z.infer<typeof PrimitiveNode>;
