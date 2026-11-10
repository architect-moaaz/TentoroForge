"use client";
// The signed-in person's plan, where the frame shows it.
//
// An app that sells plans said nothing about them outside its billing page: a
// member who paid looked like everyone else, a trial's end was a surprise, and
// in an app that stays open a new member never learned a plan existed (Task
// Board, 2026-11-06). The frame now reads the person's plan once per page load
// (`/api/billing/status`, asked, not taken from the session: an older app's
// sign-in never fills it, and it catches up only within the minute after a
// payment) and shows it: a holder's name is marked as a member's in the account
// menu, the menu says the plan and its date, and someone without one is shown
// the way to a plan — never on the plan page or a payment page.

import * as React from "react";
import { usePathname } from "next/navigation";
import { Crown, Sparkles } from "lucide-react";

export interface PlanStatus {
  /** The app sells plans at all. */
  offered: boolean;
  /** This person's plan opens the app now (active, on trial, in grace, or cancelled but paid up). */
  held: boolean;
  plan: { id: string; name: string } | null;
  /** active | trialing | past_due | cancelled | incomplete … as the gateway says. */
  status: string | null;
  /** When the period, the trial or the plan ends. */
  until: string | null;
  /** Cancelled: it ends at `until` and does not renew. */
  ending: boolean;
}

const NONE: PlanStatus = { offered: false, held: false, plan: null, status: null, until: null, ending: false };

/** One request per page load, shared by every part of the frame that asks. */
let asked: Promise<PlanStatus> | null = null;

function read(): Promise<PlanStatus> {
  if (asked) return asked;
  const base = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");
  asked = fetch(`${base}/api/billing/status`, { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((j): PlanStatus => {
      if (!j) return NONE;
      const plans: Array<{ id: string; name: string }> = Array.isArray(j.plans) ? j.plans : [];
      const sub = j.subscription ?? null;
      const plan = sub ? plans.find((p) => p.id === sub.plan) ?? { id: String(sub.plan ?? ""), name: String(sub.plan ?? "Plan") } : null;
      return {
        offered: plans.length > 0, held: Boolean(j.access && sub), plan,
        status: sub?.status ?? null, until: sub?.currentPeriodEnd ?? null,
        ending: Boolean(sub && (sub.cancelAtPeriodEnd || sub.status === "cancelled")),
      };
    })
    .catch(() => NONE);
  return asked;
}

/** The person's plan, or null while it is asked. `enabled` false (an app that sells no plans) asks nothing. */
export function usePlanStatus(enabled = true): PlanStatus | null {
  const [status, setStatus] = React.useState<PlanStatus | null>(null);
  React.useEffect(() => {
    if (!enabled) return;
    let live = true;
    void read().then((s) => { if (live) setStatus(s); });
    return () => { live = false; };
  }, [enabled]);
  return enabled ? status : NONE;
}

function day(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** The plan in a line: "Pro · renews 3 Dec 2026", "Free trial of Pro · until 20 Nov 2026"… */
export function planLine(s: PlanStatus): string {
  if (!s.plan) return "";
  const until = day(s.until);
  if (s.ending) return until ? `${s.plan.name} · ends ${until}` : `${s.plan.name} · ending`;
  if (s.status === "trialing") return until ? `Free trial of ${s.plan.name} · until ${until}` : `Free trial of ${s.plan.name}`;
  if (s.status === "past_due") return `${s.plan.name} · payment due`;
  return until ? `${s.plan.name} · renews ${until}` : s.plan.name;
}

/** A holder's mark: the crown on the avatar, in the app's own primary colour. */
export function MemberCrown({ size = 10 }: { size?: number }) {
  return (
    <span aria-hidden data-member-crown=""
      className="absolute -right-1 -top-1 grid place-items-center rounded-full bg-gradient-to-br from-amber-300 to-amber-500 p-[3px] text-amber-950 shadow ring-2 ring-background">
      <Crown size={size} strokeWidth={2.5} />
    </span>
  );
}

export function PlanPrompt() {
  const pathname = usePathname() || "/";
  const status = usePlanStatus(true);
  const base = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");
  if (!status || !status.offered || status.held || /^\/(billing|pay)(\/|$)/.test(pathname)) return null;
  return (
    <a href={`${base}/billing`} data-plan-prompt=""
      className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full bg-primary px-3.5 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90">
      <Sparkles size={14} aria-hidden /> Choose a plan
    </a>
  );
}
