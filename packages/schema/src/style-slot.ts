// packages/schema/src/style-slot.ts
import { z } from "zod";
import { SpacingTokenRef, RadiusTokenRef, ShadowTokenRef, ColorTokenRef } from "./tokens";

export const Background = z.discriminatedUnion("type", [
  z.object({ type: z.literal("solid"),    value: ColorTokenRef }),
  z.object({ type: z.literal("gradient"), from: ColorTokenRef, to: ColorTokenRef,
             angle: z.number().int().min(0).max(360).optional() }),
  z.object({ type: z.literal("image"),    url: z.string().url().or(z.string().startsWith("/")),
             overlay: ColorTokenRef.optional(),
             position: z.string().optional() }),
  z.object({ type: z.literal("pattern"),
             name: z.enum(["dots", "grid", "noise", "mesh"]),
             color: ColorTokenRef.optional() }),
]);

export const Motion = z.enum(["none", "fade-in", "fade-up", "stagger", "slide-in"]);

// `background` accepts either the structured discriminated-union form or a
// bare token string (`"tokens.color.surface.0"`) — the LLM emits both, and
// the runtime style resolver handles both shapes. Same Mustache-tolerance
// rationale as elsewhere in the schema.
//
// `passthrough()` instead of `strict()` so LLM-emitted shorthand style props
// (`marginTop`, `borderTop`, `gap`, etc.) don't fail validation. The runtime
// resolveStyle inspects only the documented keys; extras are passed through
// to the underlying CSSProperties object harmlessly.
//
// `position` is an optional structured sub-object (not a passthrough key) so
// that `type`, directional offsets, and `zIndex` are properly typed and
// validated. No env flag needed — optional fields are always backward-
// compatible; schemas without `position` keep validating + rendering unchanged.
export const PositionSlot = z.object({
  type:    z.enum(["relative", "absolute", "fixed", "sticky"]),
  top:     z.string().optional(),
  right:   z.string().optional(),
  bottom:  z.string().optional(),
  left:    z.string().optional(),
  zIndex:  z.number().int().optional(),
});

// Raw CSS sizing values (`"240px"`, `"50%"`, `"auto"`, `"32rem"`, `"1 1 0"`).
// Unlike padding/radius/shadow these are NOT token refs — the renderer emits
// them verbatim. Kept as a shared optional string so every size key validates
// the same way and documents intent.
const SizeValue = z.string().min(1);

export const StyleSlot = z.object({
  background: z.union([Background, z.string().min(1)]).optional(),
  padding:    SpacingTokenRef.optional(),
  radius:     RadiusTokenRef.optional(),
  shadow:     ShadowTokenRef.optional(),
  motion:     Motion.optional(),
  position:   PositionSlot.optional(),
  // Sizing (raw CSS). Optional + backward-compatible: schemas without them
  // validate + render exactly as before.
  width:      SizeValue.optional(),
  height:     SizeValue.optional(),
  minWidth:   SizeValue.optional(),
  maxWidth:   SizeValue.optional(),
  minHeight:  SizeValue.optional(),
  maxHeight:  SizeValue.optional(),
}).passthrough();

export type PositionSlotT = z.infer<typeof PositionSlot>;

export type StyleSlotT = z.infer<typeof StyleSlot>;
export type BackgroundT = z.infer<typeof Background>;
export type MotionT = z.infer<typeof Motion>;
