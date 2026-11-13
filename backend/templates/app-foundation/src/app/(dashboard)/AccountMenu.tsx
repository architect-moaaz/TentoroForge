"use client";
// Who is signed in, and the way out.
//
// An application people sign IN to has to let them sign OUT, and only one of
// the four shell frames had it — the persona strip, in an avatar menu. Every
// app on a rail or a top bar shipped with no way to leave the session, so a
// second person could not use the same browser and a tester could not change
// role (0l133sp2). Rendered once beside the breadcrumb, like the bell, so
// every frame carries it.

import * as React from "react";
import { Bot, CreditCard, Crown, Hotel, LogOut, User } from "lucide-react";
import { signOut } from "next-auth/react";
import { MemberCrown, planLine, usePlanStatus } from "./PlanPrompt";

function initials(name: string): string {
  // Letters only: "Candidate (demo)" read "C(" (DITANS D2, 2026-11-03).
  const parts = name.replace(/@.*$/, "").replace(/[^\p{L}\s._-]/gu, " ").split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

export function AccountMenu({ name, email, role, compact = false, extras, plans: sellsPlans = false }: {
  name?: string | null; email?: string | null; role?: string | null;
  /** The app sells plans (the layout knows): the person's plan is asked once and shown. */
  plans?: boolean;
  /** The avatar alone, for a rail with no room for a name. */
  compact?: boolean;
  /** Controls the frame has no room for beside the avatar: shown inside the menu. */
  extras?: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const box = React.useRef<HTMLDivElement>(null);
  const who = (name || email || "").trim();
  // "Connect an AI assistant" only where the owner turned the app's MCP
  // server on: asked once, the first time the menu opens.
  const [assistants, setAssistants] = React.useState<boolean | null>(null);
  React.useEffect(() => {
    if (!open || assistants !== null) return;
    const base = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");
    fetch(`${base}/api/mcp/tokens`, { cache: "no-store" })
      .then((r) => setAssistants(r.ok)).catch(() => setAssistants(false));
  }, [open, assistants]);
  // "Mews properties" only for whoever may manage them, in an application
  // that talks to Mews: the API answers everyone else 403 or 404.
  const [mews, setMews] = React.useState<boolean | null>(null);
  React.useEffect(() => {
    if (!open || mews !== null) return;
    const base = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");
    fetch(`${base}/api/mews/properties`, { cache: "no-store" })
      .then((r) => setMews(r.ok)).catch(() => setMews(false));
  }, [open, mews]);

  // THE PERSON'S PLAN, where the app sells plans: a holder is marked as a
  // member (the crown, a gold ring, the plan's name) and the menu says the plan
  // and its date. Asked once for the whole frame (`usePlanStatus`).
  const plan = usePlanStatus(sellsPlans);
  const plans = Boolean(plan?.offered);
  const member = Boolean(plan?.held);

  React.useEffect(() => {
    if (!open) return;
    const onAway = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onAway);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onAway); document.removeEventListener("keydown", onKey); };
  }, [open]);

  return (
    <div className="relative" ref={box}>
      <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        title={who ? `Signed in as ${who}${member && plan ? ` · ${planLine(plan)}` : ""}` : "Account"}
        data-member={member ? "" : undefined}
        className={(compact
          ? "inline-flex h-9 w-9 items-center justify-center rounded-full border bg-background text-sm text-foreground hover:bg-muted/50"
          : "inline-flex h-9 items-center gap-2 rounded-full border bg-background pl-1 pr-3 text-sm text-foreground hover:bg-muted/50")
          + (member ? " border-amber-400/80 shadow-[0_0_0_3px_rgba(251,191,36,0.18)] dark:border-amber-400/60" : " border-border/60")}>
        <span className={"relative inline-flex h-7 w-7 items-center justify-center rounded-full text-xs font-medium "
          + (member ? "bg-gradient-to-br from-amber-200 via-amber-300 to-amber-500 text-amber-950" : "bg-muted")}>
          {who ? initials(who) : <User size={14} aria-hidden />}
          {member && <MemberCrown size={compact ? 8 : 9} />}
        </span>
        {!compact && (
          <span className="hidden min-w-0 items-center gap-1.5 sm:inline-flex">
            <span className={"max-w-[12ch] truncate" + (member ? " font-semibold bg-gradient-to-r from-amber-600 to-amber-500 bg-clip-text text-transparent dark:from-amber-300 dark:to-amber-400" : "")}>
              {who || "Account"}</span>
            {member && plan?.plan && (
              <span data-member-plan="" className="max-w-[17ch] truncate rounded-full bg-amber-100 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-amber-800 dark:bg-amber-900/50 dark:text-amber-200">
                {plan.status === "trialing" ? `${plan.plan.name} trial` : plan.plan.name}</span>
            )}
          </span>
        )}
      </button>
      {open && (
        <div role="menu" className={"absolute z-50 mt-2 w-60 " + (compact ? "left-0" : "right-0") + " overflow-hidden rounded-lg border border-border/60 bg-background shadow-lg"}>
          <div className="border-b border-border/60 px-3 py-2">
            <p className="truncate text-sm font-medium text-foreground">{who || "Signed in"}</p>
            {role && <p className="mt-0.5 text-xs text-muted-foreground">{role}</p>}
            {plan?.plan && (
              <p data-account-plan="" className={"mt-1.5 flex max-w-full items-start gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium leading-snug "
                + (plan.status === "past_due" ? "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
                  : member ? "bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-300/60 dark:bg-amber-950/40 dark:text-amber-200"
                  : "bg-muted text-muted-foreground")}>
                {member && <Crown size={11} aria-hidden className="mt-0.5 shrink-0" />}<span>{planLine(plan)}</span>
              </p>
            )}
          </div>
          {extras && (
            <div data-account-extras="" className="flex flex-col gap-2 border-b border-border/60 px-3 py-2">
              {extras}
            </div>
          )}
          {plans && (
            <a role="menuitem" href={`${(process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "")}/billing`} data-account-billing=""
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground hover:bg-muted/50">
              <CreditCard size={14} aria-hidden /> {member ? "Plan & billing" : "Choose a plan"}
            </a>
          )}
          {assistants && (
            <a role="menuitem" href={`${(process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "")}/connect-ai`}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground hover:bg-muted/50">
              <Bot size={14} aria-hidden /> Connect an AI assistant
            </a>
          )}
          {mews && (
            <a role="menuitem" href={`${(process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "")}/mews-properties`}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground hover:bg-muted/50">
              <Hotel size={14} aria-hidden /> Mews properties
            </a>
          )}
          <button type="button" role="menuitem"
            onClick={() => {
              // UNDER THE APP'S OWN PREFIX: a bare "/login" took a Preview's
              // member to the platform's address, which answered "Not Found".
              const out = `${(process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "")}/login`;
              try { void signOut({ callbackUrl: out }); }
              catch { window.location.href = out; }   // a hard way out beats none
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground hover:bg-muted/50">
            <LogOut size={14} aria-hidden /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
