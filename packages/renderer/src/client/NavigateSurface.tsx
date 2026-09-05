"use client";
import * as React from "react";
import { useNavigator } from "./Navigator";

/**
 * NavigateSurface — a box that opens a route when pressed.
 *
 * A Container carrying `navigate` renders through this instead of a plain
 * div. It is the drawn card from a design (a list row with a title, a chip,
 * a version) that the designer made clickable; the card's look is entirely
 * its className, so nothing is added here but the affordance — pointer,
 * link role, keyboard activation — and the same Navigator seam Button uses,
 * so a routed modal opens as a modal rather than a full page load.
 */
export function NavigateSurface({
  navigate, className, style, children, ...rest
}: {
  navigate: string;
  className?: string;
  style?: React.CSSProperties;
  children?: React.ReactNode;
  [key: string]: unknown;
}) {
  const nav = useNavigator();
  const go = () => nav.push(navigate);
  return (
    <div
      {...rest}
      role="link"
      tabIndex={0}
      data-navigate={navigate}
      className={`${className ?? ""} cursor-pointer`.trim()}
      style={style}
      onClick={go}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } }}
    >
      {children}
    </div>
  );
}
