"use client";
import { useNavFlow } from "./NavFlowContext";
import { evalExpression } from "../data/expressions";

/**
 * Resolves a transition trigger to a navigation URL.
 *
 * Returns a function: navigate(trigger, params) → { url } | null
 *  - null when the trigger doesn't exist in nav-flow
 *  - { url } otherwise. Guards are evaluated against ctx; failing
 *    guards redirect to the guard's redirectTo page.
 *
 * Usage in dispatch:
 *   const navigate = useNavigate({ data, user });
 *   if (action.action === "navigate") {
 *     const r = navigate(action.trigger, action.params);
 *     if (r) window.location.href = r.url;
 *   }
 */
export function useNavigate(ctx: { data?: any; user?: any } = {}) {
  const navFlow = useNavFlow();

  return function navigate(
    trigger: string,
    params: Record<string, unknown> = {},
  ): { url: string } | null {
    // Raw path fallthrough: a schema onClick specifying
    // `{action:"navigate", target:"/some/path"}` should navigate to that
    // literal URL even when nav-flow.json doesn't declare a matching
    // named transition. Only leading-slash paths qualify — bare tokens
    // still resolve against transitions so a stray label can't race a
    // legit trigger.
    if (typeof trigger === "string" && trigger.startsWith("/")) {
      let url = trigger;
      for (const [k, v] of Object.entries(params)) {
        url = url.replace(`[${k}]`, encodeURIComponent(String(v)));
      }
      return { url };
    }
    if (!navFlow) return null;
    const t = navFlow.transitions.find((x: any) => x.trigger === trigger);
    if (!t) return null;
    let target = navFlow.pages.find((p: any) => p.id === t.to);
    if (!target) return null;
    if (target.guard) {
      const guard = navFlow.guards[target.guard];
      if (guard) {
        const ok = !!evalExpression(guard.condition, { ...ctx.data, user: ctx.user });
        if (!ok) {
          target = navFlow.pages.find((p: any) => p.id === guard.redirectTo) ?? target;
        }
      }
    }
    let url = target.route;
    for (const [k, v] of Object.entries(params)) {
      url = url.replace(`[${k}]`, encodeURIComponent(String(v)));
    }
    return { url };
  };
}
