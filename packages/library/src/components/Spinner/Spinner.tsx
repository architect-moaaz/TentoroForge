"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SpinnerPropsType } from "./Spinner.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface SpinnerProps extends SpinnerPropsType {
  style?: StyleSlotT;
}

const SIZE: Record<string, string> = { sm: "h-4 w-4 border-2", md: "h-6 w-6 border-2", lg: "h-8 w-8 border-[3px]" };

export function Spinner({ label = "Loading", size = "md", style }: SpinnerProps) {
  return (
    <span role="status" aria-label={label} data-spinner="" style={resolveStyle(style)} {...useMotion(style?.motion)}
      className="inline-flex items-center">
      <span className={`${SIZE[size]} animate-spin rounded-full border-muted border-t-primary`} />
      <span className="sr-only">{label}</span>
    </span>
  );
}
