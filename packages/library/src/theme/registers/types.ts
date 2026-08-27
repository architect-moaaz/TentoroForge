// packages/library/src/theme/registers/types.ts
import type { defaultTokens } from "../default-tokens";

/** Names of all available registers. Each maps to a bundle file in this dir. */
export type RegisterName =
  | "default"
  | "workday"
  | "linear"
  | "stripe"
  | "notion"
  | "figma";

/**
 * A register is a partial override on top of defaultTokens. Whatever the
 * bundle DOESN'T specify falls through to the default value.
 *
 * Bundles can override:
 *   - color groups (primary/secondary/surface/border palettes)
 *   - typography family choices
 *   - density / elevation / motionLevel scalars
 *   - radius.scale
 *
 * NOTE: `defaultTokens` is `as const` so its leaf types are string/number
 * literals. `PartialDeepLoose` widens leaves to their base types (string,
 * number, boolean) so bundle files can supply different values without
 * fighting the type-checker.
 */
export type RegisterBundle = {
  name: RegisterName;
  description: string;
  tokens: PartialDeepLoose<typeof defaultTokens>;
};

type Widen<T> =
  T extends string  ? string  :
  T extends number  ? number  :
  T extends boolean ? boolean :
  T;

type PartialDeepLoose<T> = {
  [K in keyof T]?: T[K] extends object ? PartialDeepLoose<T[K]> : Widen<T[K]>;
};
