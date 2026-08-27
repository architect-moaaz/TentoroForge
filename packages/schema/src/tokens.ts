import { z } from "zod";

// TokenRef historically enforced a strict dotted-form regex (e.g. `primary.500`).
// In practice the LLM-emitted schemas mix three forms — all of which the runtime
// accepts:
//   - canonical dotted refs: `tokens.spacing.1`, `tokens.color.surface.0`
//   - short scope refs:      `primary.500`
//   - design-system aliases: `lg`, `md`, `tight`
// Plus Mustache-template indirection (`{{theme.gap}}`). The library/runtime
// resolves all of these at render time. Validating the surface form here was
// out of sync with the runtime contract and was producing false-positive
// validation errors on every generated page. Drop the regex; keep the type
// alias and minimum-length so the field is documented and non-empty.
export const TokenRef = z.string().min(1);

export type TokenRef = z.infer<typeof TokenRef>;

export const StyleProps = z
  .object({
    color: TokenRef.optional(),
    background: TokenRef.optional(),
    padding: TokenRef.optional(),
    paddingX: TokenRef.optional(),
    paddingY: TokenRef.optional(),
    margin: TokenRef.optional(),
    marginX: TokenRef.optional(),
    marginY: TokenRef.optional(),
    fontSize: TokenRef.optional(),
    fontWeight: TokenRef.optional(),
    lineHeight: TokenRef.optional(),
    letterSpacing: TokenRef.optional(),
    borderRadius: TokenRef.optional(),
    borderColor: TokenRef.optional(),
    borderWidth: TokenRef.optional(),
    shadow: TokenRef.optional(),
    width: TokenRef.optional(),
    height: TokenRef.optional(),
    minWidth: TokenRef.optional(),
    maxWidth: TokenRef.optional(),
    minHeight: TokenRef.optional(),
    maxHeight: TokenRef.optional(),
    gap: TokenRef.optional(),
  })
  .strict();

export type StyleProps = z.infer<typeof StyleProps>;

// ---------------------------------------------------------------------------
// Scoped token-ref helpers
//
// Originally these enforced a canonical `tokens.<scope>.<...path>` prefix per
// scope (spacing/radius/shadow/color). In practice the runtime + library
// resolver accepts a wider surface (short aliases like `lg`, semantic enum
// names, Mustache templates), and the LLM emits a mix of all forms. The
// regexes were producing false-positives at parse time even when the runtime
// would happily render the value. Relax to a non-empty string and keep the
// distinct names so the schema still documents intent — actual leaf-token
// validation happens in cross-ref-validator + at runtime against the
// resolved token set.
// ---------------------------------------------------------------------------

export const ScopedTokenRef  = z.string().min(1);
export const SpacingTokenRef = z.string().min(1);
export const RadiusTokenRef  = z.string().min(1);
export const ShadowTokenRef  = z.string().min(1);
export const ColorTokenRef   = z.string().min(1);

export type ScopedTokenRefT = z.infer<typeof ScopedTokenRef>;

// ---------------------------------------------------------------------------
// Tokens — top-level design-token bag.
//
// Schemas here are intentionally permissive (`passthrough()` on every nested
// block) because the token set is open-ended by design: every project layers
// its own scopes (typography ramps, motion curves, brand-specific accents) on
// top of the canonical surface/accent/spacing/radius/color/shadow scopes. The
// schema only enforces structure for the keys we explicitly understand —
// notably the layered surface depth blocks (gradient, shadow) and the accent
// illustration block — and lets everything else flow through unchecked.
//
// All explicit keys are optional. Existing token files that predate any of
// these blocks parse unchanged.
// ---------------------------------------------------------------------------

/** A linear gradient definition consumed by SurfaceBackground + Hero/Card/Section. */
export const SurfaceGradient = z
  .object({
    type: z.literal("linear"),
    angle: z.number().min(0).max(360),
    from: z.string().min(1),
    to:   z.string().min(1),
  })
  .strict();

export type SurfaceGradient = z.infer<typeof SurfaceGradient>;

/** An accent illustration entry — asset path/ref plus an optional tone hint. */
export const AccentIllustration = z
  .object({
    asset: z.string().min(1),
    tone: z.enum(["positive", "neutral", "warning"]).optional(),
  })
  .strict();

export type AccentIllustration = z.infer<typeof AccentIllustration>;

export const Tokens = z
  .object({
    surface: z
      .object({
        gradient: z.record(SurfaceGradient).optional(),
        shadow:   z.record(z.string().min(1)).optional(),
      })
      .passthrough()
      .optional(),
    accent: z
      .object({
        illustration: z.record(AccentIllustration).optional(),
      })
      .passthrough()
      .optional(),
  })
  .passthrough();

export type Tokens = z.infer<typeof Tokens>;
