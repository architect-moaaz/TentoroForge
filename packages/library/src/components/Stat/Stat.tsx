"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { StatPropsType } from "./Stat.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useDensity, useElevation, useRadiusScale } from "../../theme/tokens-context";
import { useMotion } from "../../style/useMotion";

// up/down use inline hex (theming contract bans raw palette classes); neutral
// uses a semantic token class.
const TREND_COLOR: Record<string, string | undefined> = { up: "#16a34a", down: "#dc2626", neutral: undefined };

export interface StatProps extends StatPropsType { style?: StyleSlotT; }

export function Stat({ label, value, delta, trend = "neutral", caption, style }: StatProps) {
  // Per-app personality: radius scale, density padding, elevation depth.
  const radiusCls = RADIUS_SURFACE_CLASS[useRadiusScale()];
  const densityCls = { compact: "p-3", comfortable: "p-4", spacious: "p-5" }[useDensity()];
  const elevationCls = { flat: "!border-0", bordered: "", layered: "shadow-sm", floating: "shadow-lg" }[useElevation()];

  return (
    <div className={`flex flex-col gap-1 border border-border bg-card ${radiusCls} ${densityCls} ${elevationCls}`} data-stat="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <span className="text-sm text-muted-foreground">{label}</span>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold text-foreground">{value}</span>
        {delta && <span className={`text-sm font-medium ${trend === "neutral" ? "text-muted-foreground" : ""}`} style={{ color: TREND_COLOR[trend] }} data-trend={trend}>{delta}</span>}
      </div>
      {caption && <span className="text-xs text-muted-foreground">{caption}</span>}
    </div>
  );
}
