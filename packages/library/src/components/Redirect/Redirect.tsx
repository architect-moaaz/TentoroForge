"use client";
import * as React from "react";
import { useNavigator } from "@tentoroforge/renderer";
import type { RedirectPropsType } from "./Redirect.schema";
import { pathMatchesRoute, currentBrowserPath } from "../../util/routeMatch";

export interface RedirectProps extends RedirectPropsType {}

/**
 * True when `to` names the route the browser is already showing.
 *
 * Delegates to the shared route matcher so Redirect and NavLink cannot drift
 * apart on the one question they both ask — see util/routeMatch.
 */
export function isSelfRoute(to: string, currentPath: string | undefined): boolean {
  return pathMatchesRoute(to, currentPath);
}

/**
 * Route alias: replaces the current history entry with `to` on mount.
 *
 * Used by the route-dedup pass when two generated routes serve the same
 * user job — the losing route keeps existing (deep links, nav targets,
 * and the delivery gate's planned-page check all stay satisfied) but
 * lands the user on the canonical page. `replace` (not `push`) so the
 * alias never pollutes history — Back returns to wherever the user
 * actually came from.
 *
 * TWO THINGS IT REFUSES TO DO
 * ---------------------------
 * 1. **Redirect with no destination.** `to` is the whole component; an unset
 *    one used to fall through `if (to)` silently and leave the page sitting on
 *    the word "Redirecting…" forever, which reads as a hang. It now says what
 *    is actually wrong, which is the only thing an author can act on.
 * 2. **Redirect to the route it is already on.** A self-referential alias
 *    either bounces the browser once and lands somewhere unintended, or — when
 *    the target really does resolve to this page — pins the page on
 *    "Redirecting…" with no timeout and no way out. Neither is ever what an
 *    alias means, so the loop is refused at the source and the page renders
 *    normally instead of soft-locking. This is the component's job, not the
 *    host's: every renderer that mounts a Redirect has the same hazard.
 */
export function Redirect({ to, label }: RedirectProps) {
  const nav = useNavigator();
  const target = typeof to === "string" ? to.trim() : "";
  // The current path is read INSIDE the effect, never held in state that the
  // effect then depends on: `location` does not exist during SSR, and a state
  // round-trip would let the redirect fire on the first commit — before the
  // self-route test it is gated by had any value to test against.
  const [blocked, setBlocked] = React.useState<boolean>(!target);

  React.useEffect(() => {
    if (!target) {
      setBlocked(true);
      return;
    }
    const here = currentBrowserPath();
    if (isSelfRoute(target, here)) {
      setBlocked(true);
      return;
    }
    setBlocked(false);
    nav.replace(target);
    // nav identity is stable per provider; re-firing on the resolved target is
    // the correct dependency — a changed target must re-redirect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  if (blocked) {
    return (
      <p
        className="py-10 text-center text-sm text-muted-foreground"
        data-redirect-blocked={target || "unset"}
        role="status"
      >
        {target
          ? `Redirect skipped — “${target}” is this page.`
          : "Redirect — no destination set."}
      </p>
    );
  }

  return (
    <p
      className="py-10 text-center text-sm text-muted-foreground"
      data-redirect={target}
      role="status"
    >
      {label || "Redirecting…"}
    </p>
  );
}
