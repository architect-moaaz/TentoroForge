"use client";

import { useMemo } from "react";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import { Bell, LogOut, Settings, User } from "lucide-react";

// The client-side chrome for the persona-pills shell frame:
//   [brand] [Member · Instructor · Admin] [search] [🔔] [avatar ▾]
//   ────────────────────────────────────────────────────────────
//   [ Schedule · My Bookings · Membership ]   ← sub-nav row for the active persona
//
// Everything that needs live pathname awareness (active pill, active sub-nav
// link, which sub-nav row is visible) is derived from usePathname() rather
// than the previous inline-script pattern — that script raced hydration
// because it executed BEFORE the pill/sub-nav DOM existed, so the sub-nav
// stayed hidden on first paint and only appeared after the first soft-nav.
//
// The right-side slots (search, notifications, user menu) are visual/coverage
// only — they exist so the top bar reads as a real app chrome instead of a
// bare pill row. Search is non-functional; the bell has no unread state
// wiring; user menu uses <details> so no state management is needed.

export type PersonaJob = { id: string; label: string; route: string; pageId?: string };
export type PersonaScreen = { label: string; route: string; icon?: string };
export type Persona = {
  id: string;
  name: string;
  role?: string;
  jobs: PersonaJob[];
  screens?: PersonaScreen[];
};

type ChromeStyle = {
  bg: string;
  text: string;
  accent: string;
};

// The persona's navigable destinations, whatever key nav-flow used.
// PB-4 originally embedded `screens`; the current emitter writes `jobs` —
// reading only `screens` shipped an app with NO on-screen navigation
// (pills rendered, the menu row under them never did). Accept both.
function screensOf(p: Persona): PersonaScreen[] {
  if (p.screens && p.screens.length) return p.screens;
  return (p.jobs || []).map((j) => ({ label: j.label, route: j.route }));
}

// A persona pill should land somewhere persona-SPECIFIC. Every persona's
// first job is often the shared dashboard, which made all four pills
// navigate to the same place. Prefer the persona's first destination that
// no other persona shares; fall back to its first destination.
function pillTarget(p: Persona, all: Persona[]): string {
  const mine = screensOf(p).map((s) => s.route).filter(Boolean);
  if (!mine.length) return "/";
  const others = new Set(
    all.filter((o) => o.id !== p.id)
       .flatMap((o) => screensOf(o).map((s) => s.route)),
  );
  return mine.find((r) => !others.has(r)) ?? mine[0]!;
}

function pathMatchesRoute(pathname: string, route: string): boolean {
  if (!route) return false;
  if (pathname === route) return true;
  return pathname.startsWith(route + "/");
}

function findActivePersonaId(
  personas: Persona[],
  pathname: string
): string {
  // Best match wins: prefer the persona whose LONGEST owned route matches.
  let best: { id: string; length: number } | null = null;
  for (const p of personas) {
    const routes = screensOf(p).map((s) => s.route).filter(Boolean);
    for (const r of routes) {
      if (pathMatchesRoute(pathname, r)) {
        if (!best || r.length > best.length) {
          best = { id: p.id, length: r.length };
        }
      }
    }
  }
  // Fallback: first persona — better than an empty sub-nav row.
  return best?.id ?? personas[0]?.id ?? "";
}

export function PersonaChrome({
  personas,
  appName,
  chrome,
  userInitials,
}: {
  personas: Persona[];
  appName: string;
  chrome: ChromeStyle;
  userInitials?: string;
}) {
  const pathname = usePathname() || "/";
  const activePersonaId = useMemo(
    () => findActivePersonaId(personas, pathname),
    [personas, pathname]
  );
  const activePersona = personas.find((p) => p.id === activePersonaId) || null;
  const initials = (userInitials || "U").trim().slice(0, 2).toUpperCase();

  return (
    <>
      {/* The header is a full-bleed strip; the inner div holds the
       * max-w-screen-2xl content and the actual padding. This keeps the
       * top border edge-to-edge (matches the sub-nav row's border) while
       * the pills, brand, and right-side slots stay inset on ultrawide
       * viewports rather than smearing to the corners.
       *
       * ``py-3`` gives ~12px vertical breathing room above and below the
       * pill row so the pills don't kiss the viewport top edge. */}
      <header
        style={{ background: chrome.bg, color: chrome.text }}
        className="hidden md:block w-full shrink-0 border-b border-border"
      >
      <div className="mx-auto flex max-w-screen-2xl items-center justify-between gap-4 px-6 py-3">
        {/* Brand mark + wordmark, left */}
        <div className="flex items-center gap-3 shrink-0">
          <div
            aria-hidden
            className="h-9 w-9 rounded-full flex items-center justify-center text-sm font-semibold text-white"
            style={{ background: chrome.accent }}
          >
            {(appName || "A").trim().charAt(0).toUpperCase()}
          </div>
          <span
            className="text-[17px] font-semibold tracking-tight whitespace-nowrap"
            style={{ fontFamily: "var(--font-heading, var(--font-display, inherit))" }}
          >
            {appName}
          </span>
        </div>

        {/* Persona pill container, center */}
        <nav
          aria-label="Persona"
          className="flex items-center gap-1 rounded-full p-1 mx-auto"
          style={{ background: "rgba(15,18,32,0.05)" }}
        >
          {personas.map((persona) => {
            const target = pillTarget(persona, personas);
            const isActive = persona.id === activePersonaId;
            return (
              <a
                key={persona.id}
                href={target}
                data-persona-pill=""
                data-persona-id={persona.id}
                data-persona-active={isActive ? "true" : "false"}
                className="rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors"
                style={{
                  color: chrome.text,
                  background: isActive ? chrome.bg : "transparent",
                  boxShadow: isActive
                    ? "0 1px 2px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.04)"
                    : undefined,
                }}
              >
                {persona.name}
              </a>
            );
          })}
        </nav>

        {/* Right-side chrome: search + notifications + user menu */}
        <div className="flex items-center gap-3 shrink-0">
          <label className="hidden lg:flex items-center h-9 w-[240px] rounded-full bg-muted px-3 gap-2 border border-border">
            <svg
              aria-hidden="true"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="opacity-60"
            >
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            <input
              type="search"
              placeholder="Search…"
              aria-label="Search"
              className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:opacity-60"
            />
          </label>

          <button
            type="button"
            aria-label="Notifications"
            className="grid h-9 w-9 place-items-center rounded-full border border-border hover:bg-muted/50 transition-colors"
          >
            <Bell size={16} strokeWidth={2} />
          </button>

          <details className="relative">
            <summary
              className="grid h-9 w-9 cursor-pointer place-items-center rounded-full border border-border hover:bg-muted/50 transition-colors list-none [&::-webkit-details-marker]:hidden"
              aria-label="Account menu"
            >
              <span
                className="grid h-7 w-7 place-items-center rounded-full text-[11px] font-semibold text-white"
                style={{ background: chrome.accent }}
              >
                {initials}
              </span>
            </summary>
            <div
              role="menu"
              className="absolute right-0 mt-2 w-44 rounded-md border border-border bg-background shadow-lg py-1 text-[13px] z-50"
            >
              <a
                href="/profile"
                role="menuitem"
                className="flex items-center gap-2 px-3 py-2 hover:bg-muted/50 text-foreground"
              >
                <User size={14} strokeWidth={2} /> Profile
              </a>
              <a
                href="/settings"
                role="menuitem"
                className="flex items-center gap-2 px-3 py-2 hover:bg-muted/50 text-foreground"
              >
                <Settings size={14} strokeWidth={2} /> Settings
              </a>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  try {
                    void signOut({ callbackUrl: "/login" });
                  } catch {
                    // Fallback: hard nav to /login
                    window.location.href = "/login";
                  }
                }}
                className="flex w-full items-center gap-2 px-3 py-2 hover:bg-muted/50 text-foreground text-left"
              >
                <LogOut size={14} strokeWidth={2} /> Sign out
              </button>
            </div>
          </details>
        </div>
      </div>
      </header>

      {/* Second-tier sub-nav row — only the active persona's screens render.
       * Same edge-to-edge border + max-w-screen-2xl inner wrapper as the
       * pill row above, so the two rows visually align on any viewport. */}
      {activePersona && screensOf(activePersona).length > 0 && (
        <div
          className="hidden md:block border-b border-border"
          style={{ background: chrome.bg }}
        >
          <nav
            aria-label={`${activePersona.name} navigation`}
            data-persona-subnav-row={activePersona.id}
            data-persona-subnav="true"
            className="mx-auto flex max-w-screen-2xl items-center gap-1 px-6 py-2"
          >
            {screensOf(activePersona).map((screen) => {
              const isActive = pathMatchesRoute(pathname, screen.route);
              return (
                <a
                  key={screen.route}
                  href={screen.route}
                  data-nav-item=""
                  data-persona-subnav-link=""
                  data-nav-active={isActive ? "true" : "false"}
                  className="rounded-full px-3 h-8 inline-flex items-center text-[12.5px] font-medium transition-colors"
                  style={{
                    color: isActive ? chrome.accent : chrome.text,
                    background: isActive ? `${chrome.accent}14` : "transparent",
                    opacity: isActive ? 1 : 0.78,
                  }}
                >
                  {screen.label}
                </a>
              );
            })}
          </nav>
        </div>
      )}
    </>
  );
}
