// packages/library/src/types/hierarchy.ts
/**
 * Information-hierarchy primitives.
 *
 * Components use these to scale visual weight per importance/role/density.
 * The schema agent picks values per-element so the LLM can express which
 * piece of a page is the headline vs. supporting.
 */

import { z } from "zod";

/** MetricTile importance — primary tiles are 2x size, tabular numerics, big delta. */
export const ImportanceEnum = z.enum(["primary", "secondary", "tertiary"]);
export type Importance = z.infer<typeof ImportanceEnum>;

/** Hero role — headline = full bleed page header; banner = mid-page; inline = one-liner. */
export const HeroRoleEnum = z.enum(["headline", "banner", "inline"]);
export type HeroRole = z.infer<typeof HeroRoleEnum>;

/** Section role — drives padding + border treatment. */
export const SectionRoleEnum = z.enum(["headline", "content", "aside", "footer"]);
export type SectionRole = z.infer<typeof SectionRoleEnum>;

/** Card density — drives internal padding scale. */
export const CardDensityEnum = z.enum(["tight", "regular", "loose"]);
export type CardDensity = z.infer<typeof CardDensityEnum>;

/** Heading weight — display unlocks the future display-font slot (Phase 2). */
export const HeadingWeightEnum = z.enum(["light", "regular", "bold", "display"]);
export type HeadingWeight = z.infer<typeof HeadingWeightEnum>;
