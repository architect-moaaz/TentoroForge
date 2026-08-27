import type { ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useRadiusScale } from "../../theme/tokens-context";

type Elevation = "sm" | "md" | "lg" | "xl";
type Anchor = "top-left" | "top-right" | "bottom-left" | "bottom-right" | "center";

const ELEVATION_SHADOW: Record<Elevation, string> = {
  sm: "shadow-sm",
  md: "shadow-md",
  lg: "shadow-lg",
  xl: "shadow-2xl",
} as const;

function anchorStyle(anchor: Anchor, offset: string): React.CSSProperties {
  switch (anchor) {
    case "top-left":
      return { top: offset, left: offset };
    case "top-right":
      return { top: offset, right: offset };
    case "bottom-left":
      return { bottom: offset, left: offset };
    case "bottom-right":
      return { bottom: offset, right: offset };
    case "center":
      return { top: "50%", left: "50%", transform: "translate(-50%, -50%)" };
  }
}

export interface OverlayCardProps {
  title?: string;
  description?: string;
  elevation?: Elevation;
  anchor?: Anchor;
  offset?: string;
  children?: ReactNode;
  style?: StyleSlotT;
}

export function OverlayCard({
  title,
  description,
  elevation = "lg",
  anchor = "bottom-right",
  offset = "-3rem",
  children,
  style,
}: OverlayCardProps) {
  const radiusScale = useRadiusScale();

  const positionStyle: React.CSSProperties = {
    position: "absolute",
    zIndex: 10,
    ...anchorStyle(anchor, offset),
  };

  const containerClass = [
    "flex flex-col overflow-hidden border bg-card text-card-foreground",
    RADIUS_SURFACE_CLASS[radiusScale],
    ELEVATION_SHADOW[elevation],
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={containerClass}
      style={{ ...positionStyle, ...resolveStyle(style) }}
      data-anchor={anchor}
      data-elevation={elevation}
      {...useMotion(style?.motion)}
    >
      {title && (
        <div className="border-b px-6 py-4 text-base font-semibold leading-none tracking-tight">
          {title}
        </div>
      )}
      <div className="flex-1 p-6">
        {description && (
          <p className="text-sm text-muted-foreground">{description}</p>
        )}
        {children}
      </div>
    </div>
  );
}
