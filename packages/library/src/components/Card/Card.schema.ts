import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const CardProps = z
  .object({
    title: z.string().optional(),
    footer: z.string().optional(),
    elevation: z.enum(["none", "sm", "md", "lg"]).default("sm"),
    // Padding tightness. The card's theme variants (Card.figma/linear/notion)
    // already implement this prop; declaring it here closes a drift where the
    // strict schema rejected the `density` the composer legitimately emits for
    // dense dashboards ("Additional properties are not allowed ('density'…)").
    density: z.enum(["tight", "regular", "loose"]).optional(),
    // A card that opens the record it shows. The same prop, seam and
    // keyboard behaviour `Container` already carries (ContainerNode.props):
    // a collection of cards is how most designs present records, and without
    // this the only clickable card was an unstyled Container, so a card grid
    // could not offer what a table offers through `rowActions`.
    navigate: z.string().optional(),
    style: StyleSlot.optional(),
  })
  .strict();

export type CardPropsType = z.infer<typeof CardProps>;
