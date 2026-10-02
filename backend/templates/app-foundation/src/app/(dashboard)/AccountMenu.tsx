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
import { LogOut, User } from "lucide-react";
import { signOut } from "next-auth/react";

function initials(name: string): string {
  const parts = name.replace(/@.*$/, "").split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

export function AccountMenu({ name, email, role }: { name?: string | null; email?: string | null; role?: string | null }) {
  const [open, setOpen] = React.useState(false);
  const box = React.useRef<HTMLDivElement>(null);
  const who = (name || email || "").trim();

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
        title={who ? `Signed in as ${who}` : "Account"}
        className="inline-flex h-9 items-center gap-2 rounded-full border border-border/60 bg-background pl-1 pr-3 text-sm text-foreground hover:bg-muted/50">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-muted text-xs font-medium">
          {who ? initials(who) : <User size={14} aria-hidden />}
        </span>
        <span className="hidden max-w-[12ch] truncate sm:inline">{who || "Account"}</span>
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-50 mt-2 w-60 overflow-hidden rounded-lg border border-border/60 bg-background shadow-lg">
          <div className="border-b border-border/60 px-3 py-2">
            <p className="truncate text-sm font-medium text-foreground">{who || "Signed in"}</p>
            {role && <p className="mt-0.5 text-xs text-muted-foreground">{role}</p>}
          </div>
          <button type="button" role="menuitem"
            onClick={() => {
              try { void signOut({ callbackUrl: "/login" }); }
              catch { window.location.href = "/login"; }   // a hard way out beats none
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground hover:bg-muted/50">
            <LogOut size={14} aria-hidden /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
