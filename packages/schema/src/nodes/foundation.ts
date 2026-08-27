import { z } from "zod";
import { StyleSlot } from "../style-slot";
import { NodeV2Ref } from "../node-ref";

const Cta = z.object({
  label: z.string(),
  // .or() (vs discriminatedUnion) keeps the union extensible to future
  // refines/effects on individual branches; spec calls for this shape.
  action: z.object({
    type: z.literal("navigate"),
    to: z.string(),
  }).or(z.object({ type: z.literal("workflow"), name: z.string() })),
  variant: z.enum(["primary", "secondary", "ghost"]).default("primary"),
});

const ImageOrIllustration = z.object({
  kind: z.enum(["image", "illustration"]),
  src: z.string(),
  alt: z.string().optional(),
});

// Illustration slot — referenced by Hero / Section / EmptyStateRich so each
// component can render a bundled SVG (resolved by IllustrationResolver) in a
// side-by-side layout. The `slug` resolves to <basePath>/<slug>.svg; tone
// hints downstream color treatment but is purely advisory today.
const IllustrationSlot = z.object({
  slug: z.string().min(1),
  alt: z.string().optional(),
  tone: z.enum(["primary", "secondary", "muted"]).optional(),
});

export const HeroNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Hero"),
  props: z.object({
    eyebrow:  z.string().optional(),
    headline: z.string(),
    subhead:  z.string().optional(),
    layout:   z.enum(["centered", "split", "stacked"]),
    ctas:     z.array(Cta).default([]),
    media:    ImageOrIllustration.optional(),
    role:     z.enum(["headline", "banner", "inline"]).optional(),
    illustration: IllustrationSlot.optional(),
    backgroundImage: z.object({
      url:     z.string().min(1),
      overlay: z.number().min(0).max(1).default(0.4),
    }).optional(),
  }).strict(),
  style: StyleSlot.optional(),
  // children recurse through NodeV2Ref (forward reference from page.ts) so
  // any unknown node type in a child position is rejected by the union.
  children: z.lazy(() => z.array(NodeV2Ref)).optional(),
}).strict();
export type HeroNodeT = z.infer<typeof HeroNode>;

export const SectionNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Section"),
  props: z.object({
    variant:  z.enum(["plain", "feature", "cta", "stats", "split", "full-bleed"]).default("plain"),
    title:    z.string().optional(),
    subtitle: z.string().optional(),
    anchor:   z.string().optional(),
    role:     z.enum(["headline", "content", "aside", "footer"]).optional(),
    illustration: IllustrationSlot.optional(),
    // Layout escape-hatches the composer emits on rich sections. Renderer
    // consumes padding as a spacing-token classname; collapsible flips a
    // disclosure UI.
    padding: z.union([
      z.enum(["none", "sm", "md", "lg"]),
      z.string(),  // token ref like "tokens.spacing.6"
    ]).optional(),
    collapsible: z.boolean().optional(),
  }).strict(),
  style: StyleSlot.optional(),
  // children recurse through NodeV2Ref (forward reference from page.ts) so
  // any unknown node type in a child position is rejected by the union.
  children: z.lazy(() => z.array(NodeV2Ref)).default([]),
}).strict();
export type SectionNodeT = z.infer<typeof SectionNode>;

export const MetricTileNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("MetricTile"),
  props: z.object({
    label:      z.string(),
    value:      z.union([z.number(), z.string().min(1)]),
    format:     z.enum(["number", "currency", "percent", "duration"]),
    // Mustache-tolerant: LLM-generated schemas commonly bind these fields to
    // `{{stats.X}}` / `{{stats.Xtrend}}` placeholders that resolve to the
    // typed value at render time via `interpolate.ts`. Accept string here so
    // the parse step doesn't reject unresolved templates.
    delta:      z.object({
      value: z.union([z.number(), z.string().min(1)]),
      direction: z.union([z.enum(["up", "down", "flat"]), z.string().min(1)]),
    }).optional(),
    icon:       z.string().optional(),
    trend:      z.array(z.number()).optional(),
    importance: z.enum(["primary", "secondary", "tertiary"]).optional(),
    // Time window for a delta/sparkline (composer hint that widens the
    // upstream aggregate query). "week" | "month" | "quarter" | "year".
    trendWindow: z.string().optional(),
    // ── Slice A — widget anatomy (2026-08-15) ──────────────────────────
    // Optional richness fields — omission leaves the tile rendering
    // exactly as today. See docs/superpowers/specs/
    // 2026-08-15-widget-anatomy-composition-recipes.md
    //
    // breakdown — sub-lines under the primary value, e.g.
    //   "Clients 2,000 / Male 984 / Female 1,016" or
    //   "Total Debt $127M / Max $516K / Min $5". Each row is a label
    //   + value pair the composer wires to its own data source; values
    //   are strings so mustache bindings pass through unmodified.
    breakdown:  z.array(z.object({
      label: z.string().min(1),
      value: z.union([z.number(), z.string().min(1)]),
    })).optional(),
    // threshold — coloring rule applied to the primary value at render
    //   time. "warn" (amber) triggers when the numeric value is above
    //   warnAbove; "critical" (destructive) when above criticalAbove.
    //   colorOnValue toggles the actual text color; the data-threshold
    //   attribute always renders so downstream design tokens or custom
    //   CSS can key off it independently.
    threshold:  z.object({
      warnAbove:      z.number().optional(),
      criticalAbove:  z.number().optional(),
      colorOnValue:   z.boolean().optional(),
    }).optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type MetricTileNodeT = z.infer<typeof MetricTileNode>;

export const FeatureCardNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("FeatureCard"),
  props: z.object({
    title:       z.string(),
    description: z.string(),
    icon:        z.string().optional(),
    cta:         z.object({ label: z.string(), href: z.string() }).optional(),
    layout:      z.enum(["icon-top", "icon-left"]),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type FeatureCardNodeT = z.infer<typeof FeatureCardNode>;

export const CardNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Card"),
  // Card is most often emitted as a pure container — `{ type: "Card", style, children }`
  // with no props at all. All inner prop fields are already optional, so make
  // the props object itself optional too.
  props: z.object({
    title:     z.string().optional(),
    footer:    z.string().optional(),
    elevation: z.enum(["none", "sm", "md", "lg"]).optional(),
    density:   z.enum(["tight", "regular", "loose"]).optional(),
  }).strict().optional(),
  style: StyleSlot.optional(),
  // children recurse through NodeV2Ref (forward reference from page.ts) so
  // any unknown node type in a child position is rejected by the union.
  children: z.lazy(() => z.array(NodeV2Ref)).default([]),
}).strict();
export type CardNodeT = z.infer<typeof CardNode>;

// OverlayCard — floats over a sibling via absolute positioning + z-index +
// shadow elevation. Used for landing-page hero overlays where a sign-up card
// overlaps a feature image (BALA reference pattern). The parent container must
// have `position: relative` (or equivalent) for the anchor to take effect.
export const OverlayCardNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("OverlayCard"),
  props: z.object({
    title:       z.string().optional(),
    description: z.string().optional(),
    elevation:   z.enum(["sm", "md", "lg", "xl"]).default("lg"),
    // Which corner (or center) the card anchors to relative to its positioned
    // parent. "bottom-right" is the canonical BALA-style default.
    anchor:      z
      .enum(["top-left", "top-right", "bottom-left", "bottom-right", "center"])
      .default("bottom-right"),
    // CSS length applied to the inset edge(s). Negative values produce the
    // characteristic overlap-into-parent effect (e.g. "-3rem").
    offset:      z.string().default("-3rem"),
  }).strict(),
  style: StyleSlot.optional(),
  children: z.lazy(() => z.array(NodeV2Ref)).optional(),
}).strict();
export type OverlayCardNodeT = z.infer<typeof OverlayCardNode>;

export const HeadingNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Heading"),
  props: z.object({
    level:   z.number().int().min(1).max(6).optional(),
    content: z.string().min(1),
    id:      z.string().optional(),
    weight:  z.enum(["light", "regular", "bold", "display"]).optional(),
    align:   z.enum(["start", "center", "end", "left", "right"]).optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type HeadingNodeT = z.infer<typeof HeadingNode>;
