// packages/library/src/components/variants/index.ts
import * as React from "react";

import { MetricTile } from "../MetricTile/MetricTile";
import { MetricTileWorkday } from "../MetricTile/MetricTile.workday";
import { MetricTileLinear } from "../MetricTile/MetricTile.linear";
import { MetricTileStripe } from "../MetricTile/MetricTile.stripe";
import { MetricTileNotion } from "../MetricTile/MetricTile.notion";
import { MetricTileFigma } from "../MetricTile/MetricTile.figma";
import { Card } from "../Card/Card";
import { CardWorkday } from "../Card/Card.workday";
import { CardLinear } from "../Card/Card.linear";
import { CardStripe } from "../Card/Card.stripe";
import { CardNotion } from "../Card/Card.notion";
import { CardFigma } from "../Card/Card.figma";
import { Hero } from "../Hero/Hero";
import { HeroWorkday } from "../Hero/Hero.workday";
import { HeroLinear } from "../Hero/Hero.linear";
import { HeroStripe } from "../Hero/Hero.stripe";
import { HeroNotion } from "../Hero/Hero.notion";
import { HeroFigma } from "../Hero/Hero.figma";

import type { RegisterName } from "../../theme/registers";

/**
 * Runtime variant selector. Returns the register-specific variant for a
 * component, or the default when no variant exists for the given register.
 *
 * Usage in registry:
 *   `register("MetricTile", selectVariant("MetricTile", activeRegister))`
 *
 * Variants are opt-in — components without entries here always use the default.
 * Adding a new register variant requires only a new entry in VARIANTS; no
 * schema changes needed.
 */
const VARIANTS: Record<string, Partial<Record<RegisterName, React.ComponentType<any>>>> = {
  MetricTile: { workday: MetricTileWorkday, linear: MetricTileLinear, stripe: MetricTileStripe, notion: MetricTileNotion, figma: MetricTileFigma },
  Card:       { workday: CardWorkday,       linear: CardLinear,       stripe: CardStripe,       notion: CardNotion,       figma: CardFigma },
  Hero:       { workday: HeroWorkday,       linear: HeroLinear,       stripe: HeroStripe,       notion: HeroNotion,       figma: HeroFigma },
};

const DEFAULTS: Record<string, React.ComponentType<any>> = {
  MetricTile,
  Card,
  Hero,
};

/**
 * Return the register-specific variant for `name`, or the default component
 * when `register` is undefined / "default" / has no entry for this component.
 */
export function selectVariant(
  name: string,
  register: RegisterName | undefined,
): React.ComponentType<any> {
  if (!register || register === "default") return DEFAULTS[name];
  return VARIANTS[name]?.[register] ?? DEFAULTS[name];
}

export { VARIANTS, DEFAULTS };
