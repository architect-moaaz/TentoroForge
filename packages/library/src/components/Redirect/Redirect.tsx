"use client";
import * as React from "react";
import { useNavigator } from "@tentoroforge/renderer";
import type { RedirectPropsType } from "./Redirect.schema";

export interface RedirectProps extends RedirectPropsType {}

/**
 * Route alias: replaces the current history entry with `to` on mount.
 *
 * Used by the route-dedup pass when two generated routes serve the same
 * user job — the losing route keeps existing (deep links, nav targets,
 * and the delivery gate's planned-page check all stay satisfied) but
 * lands the user on the canonical page. `replace` (not `push`) so the
 * alias never pollutes history — Back returns to wherever the user
 * actually came from.
 */
export function Redirect({ to, label }: RedirectProps) {
  const nav = useNavigator();
  React.useEffect(() => {
    if (to) nav.replace(to);
    // nav identity is stable per provider; re-firing on `to` alone is the
    // correct dependency — a changed target must re-redirect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [to]);
  return (
    <p
      className="py-10 text-center text-sm text-muted-foreground"
      data-redirect={to}
      role="status"
    >
      {label || "Redirecting…"}
    </p>
  );
}
