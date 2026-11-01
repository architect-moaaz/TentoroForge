/**
 * The "Handoffs" link in the app's menu — for the people who work the handoff inbox, and only them.
 * Forge runtime — do not remove.
 *
 * Added to the menu's groups once the layout has narrowed them to the signed-in person. It can never break the
 * layout: anything unexpected leaves the menu exactly as it was.
 */
import { AGENTS } from "@/agents/registry";
import { canHandle } from "./handoff";

type Linkish = { label?: string; route?: string; icon?: string; items?: Linkish[] };

const HANDOFFS = "/handoffs";

const hasRoute = (groups: Linkish[]): boolean =>
  groups.some((g) => g.route === HANDOFFS || (Array.isArray(g.items) && hasRoute(g.items)));

export function withHandoffsLink<G extends Linkish>(groups: G[], user: { id?: unknown; role?: unknown; email?: unknown } | null | undefined): G[] {
  try {
    if (!user?.id || hasRoute(groups)) return groups;
    const me = { id: String(user.id), role: user.role ? String(user.role) : undefined, email: user.email ? String(user.email) : undefined };
    if (!AGENTS.some((a) => a.handoff && canHandle(a.handoff, me))) return groups;
    return [...groups, { label: "Handoffs", route: HANDOFFS, icon: "inbox" } as G];
  } catch {
    return groups;
  }
}
