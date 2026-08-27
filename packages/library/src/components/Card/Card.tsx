import type { ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle, resolveStyleNoBackground } from "../../style/resolveStyle";
import { dataAttrProps, withCallerClass } from "../../util/passthroughAttrs";
import { useMotion } from "../../style/useMotion";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useDensity, useElevation, useRadiusScale } from "../../theme/tokens-context";
import { SurfaceBackground } from "../surfaces/SurfaceBackground";

type SchemaDensity = "tight" | "regular" | "loose";
type SchemaElevation = "none" | "sm" | "md" | "lg";

type Props = {
  title?: string;
  footer?: string;
  /** Schema-level elevation — overrides token elevation when set. */
  elevation?: SchemaElevation;
  /** Schema-level density — overrides token density when set (undefined = use token). */
  density?: SchemaDensity;
  children?: ReactNode;
  style?: StyleSlotT;
  /** Schema-supplied class hook — appended to the computed class string. */
  className?: string;
  /** data-* attributes flow through validateProps; spread onto the root div. */
  [key: string]: unknown;
};

// Maps the schema's elevation prop to Tailwind shadow classes. Each entry
// references the project's globals.css design tokens via Tailwind's shadow
// scale, which shadcn-style themes wire to --shadow-* CSS vars.
const SCHEMA_ELEVATION_CLASSES: Record<SchemaElevation, string> = {
  none: "shadow-none",
  sm:   "shadow-sm",
  md:   "shadow-md",
  lg:   "shadow-lg",
};

// Maps density to internal body padding. Default = regular = today's p-6
// appearance so existing schemas without density see no visual change.
// Responsive: on mobile the schema density's full padding wastes viewport
// (a p-10 loose Card leaves ~275px of usable width at 375). Step it down
// one notch on <sm and one more on <xs so mobile feels tight without
// changing the desktop density feel.
const CARD_DENSITY_CLASSES: Record<SchemaDensity, string> = {
  tight:   "p-2 sm:p-3",
  regular: "p-4 sm:p-6",
  loose:   "p-5 sm:p-8 md:p-10",
};

// Wave 2: token-density fallback when schema density prop is absent.
// global comfortable → regular (p-6) = today's appearance.
const TOKEN_DENSITY_TO_CARD: Record<"compact" | "comfortable" | "spacious", SchemaDensity> = {
  compact:     "tight",
  comfortable: "regular",
  spacious:    "loose",
};

// Wave 2: token-elevation-aware shadow class.
// layered = shadow-sm = today's default (schema elevation "sm").
const TOKEN_ELEVATION_CLASSES: Record<"flat" | "bordered" | "layered" | "floating", string> = {
  flat:     "shadow-none",
  bordered: "border-2 border-border shadow-none",
  layered:  "shadow-sm",
  floating: "shadow-lg",
};

export function Card({ title, footer, elevation = "md", density, children, style, className: callerClass, ...rest }: Props) {
  const dataAttrs = dataAttrProps(rest);
  const tokenDensity = useDensity();
  const tokenElevation = useElevation();
  const radiusScale = useRadiusScale();

  // Density: schema prop wins when set; fall back to token-derived density.
  const effectiveDensity: SchemaDensity = density ?? TOKEN_DENSITY_TO_CARD[tokenDensity];

  // Elevation: schema prop wins when it departs from the default ("sm");
  // when it's the default, let the token elevation override (layered = shadow-sm = same result).
  const elevationClass = elevation !== "sm"
    ? SCHEMA_ELEVATION_CLASSES[elevation]
    : TOKEN_ELEVATION_CLASSES[tokenElevation];

  const containerClass = [
    // `min-w-0` — Card is commonly a flex/grid child (Split panels, Cluster
    // rows, dashboard grids). Without min-width:0, a wide descendant (a table,
    // a PDF preview, a Chart canvas, a filename Heading) forces the Card
    // wider than its track and busts the parent layout on mobile.
    "flex flex-col overflow-hidden border bg-card text-card-foreground min-w-0",
    RADIUS_SURFACE_CLASS[radiusScale],
    elevationClass,
  ].filter(Boolean).join(" ");
  const rootClass = withCallerClass(containerClass, callerClass);
  const bodyPadding = CARD_DENSITY_CLASSES[effectiveDensity];
  const cardBody = (
    <>
      {title && (
        <div data-slot="header" className="border-b px-6 py-4 text-base font-semibold leading-none tracking-tight">
          {title}
        </div>
      )}
      {/*
        Body uses flex column with a minimum gap so sibling children
        (badge + action, heading + description + button, etc.) always
        have breathing room even when the schema author omits a Stack
        wrapper. Explicit Stack/Row/Grid children override this via
        their own gap. Root-cause fix for the B-021.3 badge/link collision.
      */}
      <div data-slot="body" className={`flex flex-1 flex-col gap-3 ${bodyPadding}`}>{children}</div>
      {footer && (
        <div data-slot="footer" className="border-t px-6 py-3 text-sm text-muted-foreground">{footer}</div>
      )}
    </>
  );

  // When style.background is present, render an inner SurfaceBackground that
  // carries the gradient/solid backdrop, clipped to the card's existing
  // radius via rounded-[inherit]. The outer chrome (border/shadow/radius)
  // remains on the outer div. When no background, render the body directly
  // to avoid an extra wrapper div in the default case.
  return (
    <div
      data-card=""
      className={rootClass}
      style={resolveStyleNoBackground(style)}
      {...useMotion(style?.motion)}
      {...dataAttrs}
    >
      {style?.background ? (
        <SurfaceBackground
          background={style.background}
          className="flex flex-1 flex-col rounded-[inherit]"
        >
          {cardBody}
        </SurfaceBackground>
      ) : (
        cardBody
      )}
    </div>
  );
}
