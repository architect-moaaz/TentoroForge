import type * as React from "react";
import { redirect } from "next/navigation";
import { promises as fs } from "node:fs";
import path from "node:path";
import { auth } from "@/auth";
import { SideNav } from "@tentoroforge/library";
import {
  Activity, ArrowLeftRight, BarChart2, BarChart3, Bell, BookOpen, Box,
  Briefcase, Building, Calendar, CalendarCheck, CalendarClock, Car,
  CheckSquare, Circle, ClipboardList, Clock, CreditCard, Database,
  DollarSign, DoorOpen, Dumbbell, FileText, Flag, Folder, FolderKanban,
  Gavel, GitBranch, Globe, GraduationCap, Heart, HeartPulse, Home, Inbox,
  Layers, LayoutDashboard, Mail, Megaphone, Package, PieChart, Receipt,
  Scale, Search, Settings, Settings2, Shield, ShoppingCart, Star,
  Stethoscope, Tag, Target, Ticket, TrendingUp, Truck, User, UserCheck,
  UserCog, Users, Wallet, Wrench, Zap,
} from "lucide-react";
import { ShellStateProvider } from "@tentoroforge/renderer";
import { MobileNav } from "./MobileNav";
import { PersonaChrome } from "./PersonaChrome";
import { AppNavigator } from "@/components/AppNavigator";
import { schemas } from "@/schemas/registry";

// The app shell renders the generated SideNav: a collapsible rail that expands on
// hover (desktop) and becomes an off-canvas drawer with a hamburger (mobile, via
// ShellStateProvider). Its menu + colors come from the generated shell.json (which
// carries the dynamically chosen frame, palette, and grouped nav). Falls back to a
// flat menu built from nav-flow.json if shell.json is absent.

type Sub = { label: string; route: string; icon?: string };
type Group = { label?: string; icon?: string; route?: string; items?: Sub[] };
type NavProps = {
  groups: Group[];
  appName?: string;
  mode?: "dark" | "light";
  bg?: string;
  text?: string;
  muted?: string;
  accent?: string;
};
type NavPage = { route?: string; title?: string; shell?: boolean; params?: string[] };

function humanize(title: string | undefined, route: string): string {
  let raw = (title || "").replace(/(List|Detail|Create|Edit|Index)?Page$/, "");
  if (!raw) raw = route.split("/").filter(Boolean)[0] || "Home";
  raw = raw.replace(/[-_]/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2").trim();
  const label = raw
    ? raw.split(" ").map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(" ")
    : "Home";
  // "Matters List" reads as generator output — the list page IS the entity page.
  return label.replace(/\s+List$/, "") || "Home";
}

// Detail pages are reached through their list's rows, not the rail. A menu
// full of "Contract Detail" / "User Detail" entries is a same-generator tell.
function isDetailPage(title: string | undefined, route: string): boolean {
  const t = (title || "").trim();
  return /Detail(Page)?$/.test(t) || /\bDetail\s*$/.test(t) ||
    /(^|[-/])details?($|[-/])/.test(route.toLowerCase());
}

// Nav items need an icon or the rail renders blank glyphs. Map by keyword to a
// lucide-react name (the SideNav resolves these), with a stable fallback so no
// item is icon-less. Only used by the nav-flow fallback below (a shell-provided
// SideNav already carries its own icons).
const ICON_MAP: [RegExp, string][] = [
  [/dash|home|overview/, "layout-dashboard"],
  [/user|member|guest|customer|client|contact|people|staff|employee/, "users"],
  [/room|unit|property|space/, "door-open"],
  [/reserv|book|appointment|schedule|calendar/, "calendar-check"],
  [/invoice|bill|payment|transaction/, "receipt"],
  [/rate|plan|price|pricing|tariff/, "tag"],
  [/project|job|case|deal/, "folder-kanban"],
  [/task|todo|ticket|request|approval/, "check-square"],
  [/product|item|inventory|stock|catalog/, "package"],
  [/order|cart|sale|purchase/, "shopping-cart"],
  [/report|analytic|metric|stat|insight/, "bar-chart-3"],
  [/setting|config|admin|preference/, "settings"],
  [/timeline|activity|log|event/, "activity"],
  [/message|inbox|chat|mail|notification/, "inbox"],
  [/document|file|record|note/, "file-text"],
];
function iconFor(label: string, route: string): string {
  const hay = `${label} ${route}`.toLowerCase();
  for (const [re, icon] of ICON_MAP) if (re.test(hay)) return icon;
  return "circle";
}

function findSideNav(node: unknown): { props?: NavProps } | null {
  if (!node || typeof node !== "object") return null;
  const n = node as { type?: string; props?: NavProps; children?: unknown[] };
  if (n.type === "SideNav") return n;
  for (const c of n.children || []) {
    const r = findSideNav(c);
    if (r) return r;
  }
  return null;
}

const AUTH_ROUTES = new Set(["/login", "/signup"]);

// Every route already represented in a SideNav groups array — walks BOTH flat
// groups ({route}) and grouped ones ({items:[{route}]}) so the merge never
// double-lists a curated page.
function existingRoutes(groups: Group[]): Set<string> {
  const s = new Set<string>();
  for (const g of groups) {
    if (g.route) s.add(g.route);
    for (const it of g.items || []) if (it.route) s.add(it.route);
  }
  return s;
}

// Flat nav items for nav-flow shell pages not already in `have`. Mirrors the
// SideNav's visibility rules: shell:true only, no auth entries, no
// parameterized/dynamic ("[") routes, no ".../new" create routes.
function navFlowShellItems(nf: unknown, have: Set<string>): Group[] {
  const pages: NavPage[] = Array.isArray((nf as { pages?: NavPage[] })?.pages)
    ? (nf as { pages: NavPage[] }).pages
    : [];
  const out: Group[] = [];
  const seen = new Set<string>();
  for (const p of pages) {
    if (!p.shell) continue;
    if (p.params && p.params.length) continue;
    const route = p.route ?? "/";
    if (route.includes("[") || route.endsWith("/new")) continue;
    if (AUTH_ROUTES.has(route)) continue;
    if (have.has(route) || seen.has(route)) continue;
    if (isDetailPage(p.title, route)) continue;
    seen.add(route);
    const label = route === "/" ? "Dashboard" : humanize(p.title, route);
    out.push({ label, route, icon: iconFor(label, route) });
  }
  return out;
}

async function readNavFlow(): Promise<unknown> {
  const np = path.join(process.cwd(), "src", "contracts", "nav-flow.json");
  return JSON.parse(await fs.readFile(np, "utf8"));
}

// The app's own design identity for the shell. Every generated app ships a
// design-spec.json with sidebarBg/sidebarText/sidebarActiveItem — without this,
// every shell-less app rendered the identical hardcoded navy rail regardless
// of its palette (a major "all apps look the same" driver). Also carries the
// FRAME decision (sidebar | topbar) so the shell's *structure* — not just its
// paint — varies per app.
type ShellIdentity = Partial<NavProps> & {
  frame: "sidebar" | "topbar" | "persona-pills"; chrome?: string; primary?: string; density?: string;
  skin?: string;
};

// PB-6: nav-flow.personas shape emitted by services/nav_flow_from_plan when a
// product brief was synthesised. Each persona is a top-level pill in the
// persona-pills shell; jobs are its per-persona tab targets.
type NavPersonaJob = { id: string; label: string; route: string; pageId?: string };
// Slice B (2026-08-13) — persona `screens` is the archetype-vocabulary's
// primary_screens_per_persona list, resolved to real routes. Rendered as
// a second-tier sub-nav pill row below the persona pills (Schedule /
// My Bookings / Membership in the yoga demo). Optional; when absent the
// sub-nav row is skipped entirely.
type NavPersonaScreen = { label: string; route: string; icon?: string };
type NavPersona = {
  id: string; name: string; role?: string;
  jobs: NavPersonaJob[];
  screens?: NavPersonaScreen[];
};

// The content frame varies with the app's density DNA — a compact ops tool
// stretches wide with tight gutters; a spacious consumer app reads narrow and
// airy. One constant max-w-7xl frame on every app was a same-generator tell.
//
// Padding ramps up with viewport, NOT down: mobile always gets 16px so a 375px
// screen isn't half-consumed by gutters (the previous `p-8 lg:p-12` cap on
// spacious burned ~48px per side, leaving ~280px of usable content width).
function frameClass(density?: string): string {
  // Widened caps so wide viewports don't leave a large body-bg "dead ring"
  // around narrow content. Previous caps were too tight for 1920px+ displays
  // (max-w-7xl = 1280px left ~320px per side of visible body-bg — read as
  // wasted space, not intentional gutters). New caps land ~1600-1700px so
  // the framed column dominates the viewport while still centering.
  if (density === "compact") return "mx-auto w-full max-w-[1600px] p-4 md:p-4 lg:p-6";
  if (density === "spacious") return "mx-auto w-full max-w-[1560px] p-4 md:p-8 lg:p-12";
  return "mx-auto w-full max-w-[1600px] p-4 md:p-6 lg:p-8";
}

async function shellIdentity(): Promise<ShellIdentity> {
  try {
    const dp = path.join(process.cwd(), "src", "contracts", "design-spec.json");
    const spec = JSON.parse(await fs.readFile(dp, "utf8"));
    const pal = (spec?.colorPalette ?? {}) as Record<string, string>;
    const hex = (v?: string) => (typeof v === "string" && /^#[0-9a-fA-F]{6}/.test(v.trim())
      ? v.trim().slice(0, 7) : undefined);
    const bg = hex(pal.sidebarBg);
    const text = hex(pal.sidebarText);
    const accent = hex(pal.sidebarActiveItem) ?? hex(pal.accent) ?? hex(pal.primary);
    // Perceived luminance decides light-vs-dark rail chrome.
    let mode: "dark" | "light" = "dark";
    if (bg) {
      const r = parseInt(bg.slice(1, 3), 16), g = parseInt(bg.slice(3, 5), 16), b = parseInt(bg.slice(5, 7), 16);
      mode = (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? "light" : "dark";
    }
    const nav = String((spec?.layout ?? {}).navigation ?? "sidebar").toLowerCase();
    let frame: "sidebar" | "topbar" | "persona-pills" = nav.includes("topbar") || nav.includes("top-nav")
      ? "topbar" : "sidebar";
    // Phase 4 (renderer↔schema contract unification): shell.json.frame is the
    // deterministic frame decision made by services/shell_templates.select_frame
    // — informed by IA + nav_flow, not just design_spec. Prefer it when
    // present so shell.json.frame is authoritative, not silently ignored.
    // Legacy values ("rail" | "none") collapse to "sidebar"; "persona-pills"
    // (PB-3) surfaces as its own top-strip frame, rendered from
    // nav-flow.personas rather than the entity-grouped SideNav.
    try {
      const shellPath = path.join(process.cwd(), "src", "schemas", "shell.json");
      const shellJson = JSON.parse(await fs.readFile(shellPath, "utf8"));
      const shellFrame = String(shellJson?.frame ?? "").toLowerCase();
      if (shellFrame === "topbar") frame = "topbar";
      else if (shellFrame === "persona-pills") frame = "persona-pills";
      else if (shellFrame === "sidebar" || shellFrame === "rail" || shellFrame === "none") frame = "sidebar";
    } catch { /* shell.json missing/unreadable — keep design-spec-derived frame */ }
    // Shell CHROME — the structural style of the navigation itself, chosen by
    // the app's design DNA. This is what stops every generated app from
    // shipping the identical hover-expand rail.
    let chrome = String((spec?.layout ?? {}).chrome ?? "standard-rail");
    let skin = String(spec?.skin ?? "");
    try {
      const dnaRaw = await fs.readFile(
        path.join(process.cwd(), "src", "contracts", "design-dna.json"), "utf8");
      const dna = JSON.parse(dnaRaw);
      chrome = String(dna?.layout?.chrome ?? dna?.shell?.chrome ?? chrome);
      skin = String(dna?.skin ?? "");
    } catch { /* design-dna optional */ }
    const density = String((spec?.layout ?? {}).density ?? "comfortable");
    return { frame, chrome, density, skin, ...(bg ? { bg } : {}), ...(text ? { text } : {}),
             ...(accent ? { accent } : {}), mode, primary: hex(pal.primary) };
  } catch {
    return { frame: "sidebar", chrome: "standard-rail", mode: "dark" };
  }
}

// Last-resort menu: when NEITHER the generated shell NOR nav-flow yields a
// single nav item, derive one from the schema registry — every "<entity>/list"
// schema becomes a nav entry, plus a Dashboard link. This is the final guard
// against a blank rail: whatever goes wrong upstream (missing/empty shell.json,
// an all-filtered nav-flow), the app STILL ships a working menu with a
// Dashboard. Empty-menu was the "no menus / no dashboard" demo failure.
function schemaRegistryItems(): Group[] {
  const seen = new Set<string>(["/"]);
  const out: Group[] = [{ label: "Dashboard", route: "/", icon: "layout-dashboard" }];
  const keys = Object.keys(schemas);
  // Old registry format: "<entity>/list" keys (no leading slash).
  const listRoutes = keys
    .filter((k) => k.endsWith("/list"))
    .map((k) => "/" + k.split("/")[0]);
  // Current registry format: route keys ("/appointments", "/admin/users", …).
  // Keep only top-level, non-dynamic, non-CRUD routes — the entity landings a
  // rail should link to.
  const INFRA = new Set(["/shell", "/dashboard", "/home", "/index"]);
  const routeRoutes = keys
    .filter((k) => k.startsWith("/") && !k.includes("["))
    .filter((k) => !/\/(new|edit|list)$/.test(k))
    .filter((k) => k.split("/").filter(Boolean).length === 1)
    .filter((k) => !AUTH_ROUTES.has(k) && !INFRA.has(k));
  for (const r of [...listRoutes, ...routeRoutes].sort()) {
    if (seen.has(r) || r === "/") continue;
    seen.add(r);
    const label = humanize(undefined, r);
    out.push({ label, route: r, icon: iconFor(label, r) });
  }
  return out;
}

/** Flatten SideNav groups (flat + grouped) into one ordered nav-link list. */
function flattenNav(groups: Group[]): Sub[] {
  const out: Sub[] = [];
  for (const g of groups) {
    if (g.route) out.push({ label: g.label ?? g.route, route: g.route, icon: g.icon });
    for (const it of g.items || []) if (it.route) out.push(it);
  }
  return out;
}

/**
 * The TOPBAR shell frame — a premium horizontal header nav, painted with the
 * app's identity. Server component; plain anchors (AppNavigator soft-navigates
 * them). Mobile: the link row scrolls horizontally instead of collapsing, so
 * every destination stays reachable without client-side chrome.
 */
function TopNav({ items, appName, id }: { items: Sub[]; appName: string; id: ShellIdentity }) {
  const dark = id.mode !== "light";
  const bg = id.bg ?? (dark ? "#101418" : "#ffffff");
  const text = id.text ?? (dark ? "#cbd5e1" : "#334155");
  const accent = id.accent ?? id.primary ?? "#2563eb";
  return (
    <>
      {/* Mobile: hamburger + slide-in drawer (client component). Shown only
       * <md; the desktop <header> below is `hidden md:flex`, so they swap
       * cleanly at the breakpoint without ever both being visible. */}
      <MobileNav appName={appName} items={items} bg={bg} text={text} />
      <header
        style={{ background: bg, color: text, borderBottom: dark ? "none" : "1px solid rgba(0,0,0,0.08)" }}
        className="hidden md:flex h-14 shrink-0 items-center gap-6 px-4 lg:px-6"
      >
        <span className="text-[15px] font-semibold tracking-tight whitespace-nowrap" style={{ fontFamily: "var(--font-heading)" }}>
          {appName}
        </span>
        <nav data-shell-nav="" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {items.map((it) => (
            <a
              key={it.route}
              href={it.route}
              data-nav-item=""
              className="whitespace-nowrap rounded-md px-3 py-1.5 text-[13px] opacity-80 transition-opacity hover:opacity-100"
              style={{ color: text }}
            >
              <span data-nav-label="">{it.label}</span>
            </a>
          ))}
        </nav>
        <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: accent }} />
      </header>
    </>
  );
}

/**
 * PB-6 (2026-08-13 refactor): the persona-pills chrome is now rendered
 * by the ``PersonaChrome`` client component (see ./PersonaChrome.tsx).
 * The previous server-side inline-script approach raced hydration —
 * the tracker's ``querySelectorAll`` executed BEFORE the pill / sub-nav
 * DOM was parsed, so the sub-nav row stayed ``display:none`` until the
 * first soft-nav. Using ``usePathname()`` in a client component makes
 * active-pill + sub-nav visibility server-safe AND hydration-safe.
 *
 * This wrapper is kept only for the (unlikely) call sites that still
 * type against the old signature; it just forwards to PersonaChrome.
 */
function PersonaPillsNav({ personas, appName, id, userInitials }: {
  personas: NavPersona[]; appName: string; id: ShellIdentity; userInitials?: string;
}) {
  const bg = id.bg ?? "#ffffff";
  const text = id.text ?? "#1a1f28";
  const accent = id.accent ?? id.primary ?? "#2563eb";
  return (
    <PersonaChrome
      personas={personas}
      appName={appName}
      chrome={{ bg, text, accent }}
      userInitials={userInitials}
    />
  );
}

/** ── LEGACY (2026-08-13): the original inline-script version, no
 *  longer emitted. Kept commented out for one release cycle so a
 *  regression can diff against it. */
function _LegacyPersonaPillsNav({ personas, appName, id }: {
  personas: NavPersona[]; appName: string; id: ShellIdentity;
}) {
  const bg = id.bg ?? "#ffffff";
  const text = id.text ?? "#1a1f28";
  const accent = id.accent ?? id.primary ?? "#2563eb";
  // Client-side script: mark the pill whose persona owns the current URL
  // as active by setting [data-persona-active="true"], and mark the
  // corresponding sub-nav row as visible via [data-persona-subnav].
  // The sub-nav pills carry [data-nav-item] so the existing activeTracker
  // handles their per-link active state. Re-runs on soft nav.
  //
  // Slice B (2026-08-13) — the sub-nav row rendering:
  //   1. All persona sub-nav rows render server-side but start hidden.
  //   2. The active-persona pass toggles [data-persona-subnav="true"]
  //      on the row matching the current URL prefix.
  //   3. That flip is what actually shows the second-tier pills.
  const activePersonaTracker = `(function(){function m(){var pills=document.querySelectorAll("[data-persona-pill]");var subnavs=document.querySelectorAll("[data-persona-subnav-row]");var url=location.pathname;var activeId="";pills.forEach(function(a){var routes=(a.getAttribute("data-persona-routes")||"").split("|").filter(Boolean);var hit=routes.some(function(r){return url===r||url.indexOf(r+"/")===0});a.setAttribute("data-persona-active",String(hit));if(hit)activeId=a.getAttribute("data-persona-id")||"";});subnavs.forEach(function(s){s.setAttribute("data-persona-subnav",String(s.getAttribute("data-persona-subnav-row")===activeId));});}m();addEventListener("popstate",m);var p=history.pushState;history.pushState=function(){p.apply(this,arguments);setTimeout(m,0)}})()`;
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: activePersonaTracker }} />
      <header
        style={{ background: bg, color: text }}
        className="hidden md:flex h-16 shrink-0 items-center justify-between px-6 lg:px-8"
      >
        {/* Brand mark + wordmark, left */}
        <div className="flex items-center gap-3">
          <div
            aria-hidden
            className="h-9 w-9 rounded-full flex items-center justify-center text-sm font-semibold text-white"
            style={{ background: accent }}
          >
            {(appName || "A").trim().charAt(0).toUpperCase()}
          </div>
          <span
            className="text-[17px] font-semibold tracking-tight whitespace-nowrap"
            style={{ fontFamily: "var(--font-heading)" }}
          >
            {appName}
          </span>
        </div>
        {/* Persona pill container, right */}
        <nav
          aria-label="Persona"
          className="flex items-center gap-1 rounded-full p-1"
          style={{ background: "rgba(15,18,32,0.05)" }}
        >
          {personas.map((persona) => {
            const jobs = persona.jobs || [];
            const first = jobs[0];
            const target = first?.route ?? "/";
            // Slice B (2026-08-13) — persona pill "owns" both its jobs'
            // routes AND its screens' routes so the active-persona pass
            // catches URLs that only appear in the second-tier sub-nav.
            const screens = persona.screens || [];
            const allRoutes = [
              ...jobs.map((j) => j.route),
              ...screens.map((s) => s.route),
            ].filter(Boolean).join("|");
            return (
              <a
                key={persona.id}
                href={target}
                data-persona-pill=""
                data-persona-id={persona.id}
                data-persona-routes={allRoutes}
                data-persona-active="false"
                className="rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors"
                style={{
                  color: text,
                  // Inactive by default; the [data-persona-active="true"]
                  // rule below flips it to a filled pill.
                }}
              >
                {persona.name}
              </a>
            );
          })}
        </nav>
      </header>
      {/* Slice B (2026-08-13) — second-tier sub-nav row per persona.
       * One row per persona is rendered (all initially hidden); the
       * active-persona tracker flips [data-persona-subnav="true"] on
       * the row whose persona owns the current URL. Personas with no
       * screens produce no row at all (the map returns null). */}
      {personas.some((p) => (p.screens || []).length > 0) && (
        <div
          className="hidden md:block"
          style={{ background: bg, borderBottom: "1px solid rgba(15,18,32,0.06)" }}
        >
          {personas.map((persona) => {
            const screens = persona.screens || [];
            if (!screens.length) return null;
            return (
              <nav
                key={`subnav-${persona.id}`}
                aria-label={`${persona.name} navigation`}
                data-persona-subnav-row={persona.id}
                data-persona-subnav="false"
                className="items-center gap-1 px-6 lg:px-8 py-2 flex"
                style={{
                  // Rows are display:none by default; the active row is
                  // flipped to display:flex via [data-persona-subnav="true"].
                  display: "none",
                }}
              >
                {screens.map((screen) => (
                  <a
                    key={screen.route}
                    href={screen.route}
                    data-nav-item=""
                    data-persona-subnav-link=""
                    data-nav-active="false"
                    className="rounded-full px-3 h-8 inline-flex items-center text-[12.5px] font-medium transition-colors"
                    style={{ color: text, opacity: 0.75 }}
                  >
                    {screen.label}
                  </a>
                ))}
              </nav>
            );
          })}
        </div>
      )}
      {/* Mobile: keep the existing MobileNav drawer working. */}
      <style dangerouslySetInnerHTML={{ __html: `
        [data-persona-pill][data-persona-active="true"] {
          background: ${bg};
          box-shadow: 0 1px 2px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.04);
        }
        [data-persona-pill][data-persona-active="false"]:hover {
          background: rgba(255,255,255,0.6);
        }
        /* Slice B — flip only the active persona's sub-nav row into view. */
        [data-persona-subnav-row][data-persona-subnav="true"] { display: flex !important; }
        [data-persona-subnav-link][data-active="true"],
        [data-persona-subnav-link][data-nav-active="true"] {
          background: ${accent}14;
          color: ${accent};
          opacity: 1;
        }
        [data-persona-subnav-link]:hover { opacity: 1; }
      ` }} />
    </>
  );
}

async function readNavPersonas(): Promise<NavPersona[]> {
  try {
    const nf = await readNavFlow() as { personas?: NavPersona[] };
    return Array.isArray(nf?.personas) ? nf.personas : [];
  } catch {
    return [];
  }
}

async function readShellAppName(): Promise<string | undefined> {
  // 2026-08-13 — shell.json now carries a top-level `appName` string
  // (shell_templates.build_shell_deterministic). Prefer it so the
  // persona-pills frame (which has no SideNav to dig it out of) still
  // gets a real brand name instead of the "Document Intelligence" placeholder.
  try {
    const sp = path.join(process.cwd(), "src", "schemas", "shell.json");
    const shell = JSON.parse(await fs.readFile(sp, "utf8")) as { appName?: unknown };
    if (typeof shell.appName === "string" && shell.appName.trim()) {
      return shell.appName.trim();
    }
  } catch { /* shell.json missing/unreadable */ }
  return undefined;
}

async function loadNavProps(): Promise<NavProps> {
  // Prefer the generated shell — it already computed the frame, palette, and
  // curated groups. But that menu is FROZEN at generation time, so any page
  // added later (a refine pass, or the visual editor's addPage) is missing
  // from it. MERGE in nav-flow shell pages the curated menu doesn't already
  // list, appended after the curated groups — so an editor-added page is never
  // orphaned from the sidebar, while the hand-curated grouping is preserved.
  const topLevelAppName = await readShellAppName();
  try {
    const sp = path.join(process.cwd(), "src", "schemas", "shell.json");
    const shell = JSON.parse(await fs.readFile(sp, "utf8"));
    const sn = findSideNav(shell);
    if (sn?.props?.groups?.length) {
      const props = sn.props;
      if (topLevelAppName && (!props.appName || props.appName === "Document Intelligence")) {
        props.appName = topLevelAppName;
      }
      try {
        const extra = navFlowShellItems(await readNavFlow(), existingRoutes(props.groups));
        if (extra.length) props.groups = [...props.groups, ...extra];
      } catch {
        /* nav-flow missing/unreadable — keep the curated shell menu as-is */
      }
      return props;
    }
  } catch {
    /* fall through to the nav-flow-only menu */
  }
  // Fallback: a flat menu from nav-flow (shell.json absent entirely), painted
  // with the app's OWN design identity instead of the hardcoded navy rail.
  const { frame: _f, primary: _p, ...rail } = await shellIdentity();
  let groups: Group[] = [];
  try {
    groups = navFlowShellItems(await readNavFlow(), new Set());
  } catch {
    /* nav-flow missing/unreadable — fall through to the registry menu */
  }
  // The rail must NEVER be empty. If nav-flow gave nothing (missing, or every
  // page filtered out), synthesize a menu from the schema registry so the app
  // always has navigation + a Dashboard.
  if (!groups.length) groups = schemaRegistryItems();
  return { groups, appName: topLevelAppName || "Document Intelligence", ...rail };
}


// ── Shell CHROME variants ───────────────────────────────────────────────────
// Five structurally different navigation shells, chosen per app by the design
// DNA. The single hover-expand SideNav used to be the only shell — the most
// visible "every app looks the same" signal.

// Covers the FULL icon vocabulary the shell generator emits (plus common
// LLM-authored names). The audit found 12/18 nav items rendering the Circle
// fallback because this map knew 16 names while shell.json used 42.
const GLYPHS: Record<string, React.ComponentType<{ size?: number; strokeWidth?: number }>> = {
  "layout-dashboard": LayoutDashboard, users: Users, "door-open": DoorOpen,
  "calendar-check": CalendarCheck, receipt: Receipt, tag: Tag,
  "folder-kanban": FolderKanban, "check-square": CheckSquare, package: Package,
  "shopping-cart": ShoppingCart, "bar-chart-3": BarChart3, settings: Settings,
  activity: Activity, inbox: Inbox, "file-text": FileText, circle: Circle,
  "arrow-left-right": ArrowLeftRight, "bar-chart-2": BarChart2, bell: Bell,
  "book-open": BookOpen, book: BookOpen, box: Box, briefcase: Briefcase,
  building: Building, calendar: Calendar, "calendar-clock": CalendarClock,
  car: Car, chart: BarChart3, "clipboard-list": ClipboardList, clock: Clock,
  "credit-card": CreditCard, database: Database, "dollar-sign": DollarSign,
  dumbbell: Dumbbell, flag: Flag, folder: Folder, gavel: Gavel,
  "git-branch": GitBranch, globe: Globe, "graduation-cap": GraduationCap,
  heart: Heart, "heart-pulse": HeartPulse, home: Home, layers: Layers,
  "layout-kanban": FolderKanban, mail: Mail, megaphone: Megaphone,
  "pie-chart": PieChart, scale: Scale, search: Search,
  stethoscope: Stethoscope, "settings-2": Settings2,
  shield: Shield, star: Star, target: Target, ticket: Ticket,
  "trending-up": TrendingUp, truck: Truck, user: User,
  "user-check": UserCheck, "user-cog": UserCog, wallet: Wallet,
  wrench: Wrench, zap: Zap,
};

function RailGlyph({ name, size = 17 }: { name?: string; size?: number }) {
  const C = GLYPHS[(name || "circle").toLowerCase()] ?? Circle;
  return <C size={size} strokeWidth={2} />;
}

/** Wide sectioned rail: 272px, uppercase group labels, pill actives, footer. */
function WideRail({ props, appName }: { props: NavProps; appName: string }) {
  const dark = props.mode !== "light";
  const bg = props.bg ?? (dark ? "#141a18" : "#ffffff");
  const text = props.text ?? (dark ? "#c9d2ce" : "#3f4a45");
  const accent = props.accent ?? "#5B8DEF";
  const pillBg = dark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.06)";
  return (
    <nav data-shell-nav="" className="hidden h-full shrink-0 flex-col overflow-y-auto md:flex"
      style={{ width: "var(--sk-nav-w, 272px)", background: bg, color: text,
               borderRight: dark ? "none" : "1px solid rgba(0,0,0,0.08)" }}>
      <div className="flex items-center gap-2.5 px-5 pb-2 pt-5">
        <span className="grid h-8 w-8 place-items-center rounded-[var(--radius)] text-sm font-bold text-white"
          style={{ background: accent }}>{appName.slice(0, 1)}</span>
        <span className="text-[15px] font-semibold tracking-tight"
          style={{ fontFamily: "var(--font-heading)" }}>{appName}</span>
      </div>
      <div className="flex-1 px-3 py-3">
        {props.groups.map((g, gi) => (
          <div key={gi} className="mb-1.5">
            {g.items?.length ? (
              <>
                <div data-nav-group-label="" className="px-2.5 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-[0.12em] opacity-55">
                  {g.label ?? ""}
                </div>
                {g.items.map((it) => (
                  <a key={it.route} href={it.route} data-nav-item=""
                    className="mb-0.5 flex items-center gap-2.5 rounded-full px-3 py-[7px] text-[13px] opacity-85 transition hover:opacity-100"
                    style={{ color: text }}>
                    <span data-nav-icon="" className="inline-flex"><RailGlyph name={it.icon} size={16} /></span>
                    <span data-nav-label="">{it.label}</span>
                  </a>
                ))}
              </>
            ) : g.route ? (
              <a href={g.route} data-nav-item=""
                className="mb-0.5 flex items-center gap-2.5 rounded-full px-3 py-[7px] text-[13px] opacity-85 transition hover:opacity-100"
                style={{ color: text }}>
                <span data-nav-icon="" className="inline-flex"><RailGlyph name={g.icon} size={16} /></span>
                <span data-nav-label="">{g.label ?? g.route}</span>
              </a>
            ) : null}
          </div>
        ))}
      </div>
      <div className="mx-3 mb-4 flex items-center gap-2.5 rounded-[var(--radius)] px-3 py-2.5"
        style={{ background: pillBg }}>
        <span className="grid h-7 w-7 place-items-center rounded-full text-[11px] font-semibold text-white"
          style={{ background: accent }}>A</span>
        <span className="text-xs opacity-80">Account</span>
      </div>
    </nav>
  );
}

/** Icon-only rail: 64px of pure glyphs — dense, technical, maximal canvas. */
function IconRail({ props, appName }: { props: NavProps; appName: string }) {
  const dark = props.mode !== "light";
  const bg = props.bg ?? (dark ? "#101418" : "#ffffff");
  const text = props.text ?? (dark ? "#c7d2de" : "#334155");
  const accent = props.accent ?? "#5B8DEF";
  const items = flattenNav(props.groups);
  return (
    <nav data-shell-nav="" className="hidden h-full shrink-0 flex-col items-center overflow-y-auto md:flex"
      style={{ width: "var(--sk-nav-w, 64px)", background: bg, color: text,
               borderRight: dark ? "none" : "1px solid rgba(0,0,0,0.08)" }}>
      <span className="mb-4 mt-4 grid h-9 w-9 place-items-center rounded-[var(--radius)] text-sm font-bold text-white"
        style={{ background: accent }}>{appName.slice(0, 1)}</span>
      <div className="flex flex-1 flex-col items-center gap-1 pb-4">
        {items.map((it) => (
          <a key={it.route} href={it.route} title={it.label} data-nav-item=""
            className="grid h-10 w-10 place-items-center rounded-[var(--radius)] opacity-75 transition hover:opacity-100"
            style={{ color: text }}>
            <span data-nav-icon="" className="inline-flex"><RailGlyph name={it.icon} size={18} /></span>
          </a>
        ))}
      </div>
    </nav>
  );
}

/** DOCK — floating bottom-centre bar; content runs full-bleed above it.
 *  A structurally different nav pattern (not a rail, not a topbar). */
function DockNav({ props, appName }: { props: NavProps; appName: string }) {
  const dark = props.mode !== "light";
  const bg = props.bg ?? (dark ? "rgba(16,20,24,.92)" : "rgba(255,255,255,.94)");
  const text = props.text ?? (dark ? "#c7d2de" : "#334155");
  // Show EVERY page — never silently drop menu items. The dock scrolls
  // horizontally if there are more than fit (was `.slice(0, 8)`, which made
  // pages 9+ unreachable on dock-chrome apps).
  const items = flattenNav(props.groups);
  return (
    <nav data-shell-nav="" data-dock=""
      className="fixed bottom-4 left-1/2 z-40 flex max-w-[calc(100vw-1rem)] -translate-x-1/2 items-center gap-1 overflow-x-auto rounded-2xl px-2 py-1.5 shadow-2xl backdrop-blur"
      style={{ background: bg, color: text, border: "1px solid rgba(127,127,127,.18)" }}>
      <span className="mx-1.5 text-[13px] font-bold tracking-tight" style={{ fontFamily: "var(--font-heading)" }}>
        {appName.slice(0, 1)}
      </span>
      {items.map((it) => (
        <a key={it.route} href={it.route} data-nav-item="" title={it.label}
          className="flex flex-col items-center gap-0.5 rounded-xl px-2.5 py-1.5 opacity-80 transition hover:opacity-100"
          style={{ color: text }}>
          <span data-nav-icon="" className="inline-flex"><RailGlyph name={it.icon} size={17} /></span>
          <span data-nav-label="" className="text-[10px] leading-none">{it.label.split(" ")[0]}</span>
        </a>
      ))}
    </nav>
  );
}

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  if (!session) redirect("/login");

  const navProps = await loadNavProps();
  const identity = await shellIdentity();
  const appName = navProps.appName || "Document Intelligence";

  // TOPBAR frame — chosen by the app's design identity (layout.navigation).
  // A structurally different shell, not just different paint.
  // Highlights the current destination in every rail/dock (server components
  // can't know the URL; this tiny tracker follows soft navigations too).
  const activeTracker = `(function(){function m(){document.querySelectorAll("[data-nav-item]").forEach(function(a){a.setAttribute("data-active",String(a.getAttribute("href")===location.pathname))})}m();addEventListener("popstate",m);var p=history.pushState;history.pushState=function(){p.apply(this,arguments);m()}})()`;
  const trackerTag = <script dangerouslySetInnerHTML={{ __html: activeTracker }} />;
  // PB-6: persona-pills frame — the Claude-yoga-demo top-strip. When the
  // deterministic shell picker (services/shell_templates.select_frame) chose
  // "persona-pills" (i.e. 2-4 personas in nav-flow.personas, attached by
  // PB-4 when a product brief was synthesised), render a top pill switcher
  // instead of any sidebar/rail. If personas somehow arrive empty (defensive
  // — the picker shouldn't have chosen this frame in that case), fall
  // through to the normal branches below rather than shipping empty chrome.
  if (identity.frame === "persona-pills") {
    const personas = await readNavPersonas();
    if (personas.length >= 2) {
      // Session user initials feed the top-bar avatar. Falls back to "U"
      // in the client component when name/email are absent.
      const rawName = (session?.user?.name || session?.user?.email || "").trim();
      const userInitials = rawName
        ? rawName
            .split(/[\s@.]+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((s) => s[0]!)
            .join("")
        : undefined;
      return (
        <ShellStateProvider>
          <AppNavigator>
            <div data-skin={identity.skin || undefined} className="flex h-screen flex-col overflow-hidden bg-background">
              {trackerTag}
              <PersonaPillsNav
                personas={personas}
                appName={appName}
                id={identity}
                userInitials={userInitials}
              />
              <main data-shell-main className="min-h-0 flex-1 overflow-y-auto">
                <div className={frameClass(identity.density)}>{children}</div>
              </main>
            </div>
          </AppNavigator>
        </ShellStateProvider>
      );
    }
    // Personas array empty despite frame=persona-pills — fall through to
    // topbar (safer than an empty chrome header).
  }

  // The DNA's chrome choice is authoritative. It used to be checked only in
  // the branch BELOW, so `chrome: "topbar"` silently fell through to the
  // default sidebar — an app that chose a horizontal nav shipped a rail
  // identical to every other app's (verified live on two generations).
  if (identity.chrome === "topbar" || identity.frame === "topbar") {
    return (
      <ShellStateProvider>
        <AppNavigator>
          <div data-skin={identity.skin || undefined} className="flex h-screen flex-col overflow-hidden bg-background">
            {trackerTag}
            <TopNav items={flattenNav(navProps.groups)} appName={appName} id={identity} />
            <main data-shell-main className="min-h-0 flex-1 overflow-y-auto">
              <div className={frameClass(identity.density)}>{children}</div>
            </main>
          </div>
        </AppNavigator>
      </ShellStateProvider>
    );
  }

  // The shell CHROME — five structurally different navigation shells. The
  // choice was made by this app's design DNA; every branch is painted from the
  // app's own identity, so both structure AND surface differ per app.
  const chrome = identity.chrome ?? "standard-rail";
  const main = (
    <main data-shell-main className="flex-1 overflow-y-auto min-w-0 h-full">
      <div className={frameClass(identity.density)}>{children}</div>
    </main>
  );
  // Mobile navigation for the rail chromes (they are `hidden md:flex`, so they
  // vanish below 768px). Shown only below md; complements the desktop rail.
  const mobileNav = (
    <MobileNav
      appName={appName}
      items={flattenNav(navProps.groups)}
      bg={navProps.bg}
      text={navProps.text}
    />
  );
  let shell: React.ReactNode;
  if (chrome === "wide-rail") {
    shell = (
      <div className="flex h-screen flex-col overflow-hidden bg-background">
        {mobileNav}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <WideRail props={navProps} appName={appName} />{main}
        </div>
      </div>
    );
  } else if (chrome === "icon-rail") {
    shell = (
      <div className="flex h-screen flex-col overflow-hidden bg-background">
        {mobileNav}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <IconRail props={navProps} appName={appName} />{main}
        </div>
      </div>
    );
  } else if (chrome === "dock") {
    // No rail at all — a floating bottom dock; content runs full-bleed.
    shell = (
      <div className="relative h-screen overflow-hidden bg-background">
        <main data-shell-main className="h-full overflow-y-auto pb-24">
          <div className={frameClass(identity.density)}>{children}</div>
        </main>
        <DockNav props={navProps} appName={appName} />
      </div>
    );
  } else if (chrome === "right-rail") {
    // Navigation on the RIGHT — content leads, nav follows. One more axis on
    // which two apps can be spatially different products.
    shell = (
      <div className="flex h-screen flex-col overflow-hidden bg-background">
        {mobileNav}
        <div className="flex min-h-0 flex-1 flex-row-reverse overflow-hidden">
          <WideRail props={navProps} appName={appName} />{main}
        </div>
      </div>
    );
  } else if (chrome === "floating-rail") {
    // The rail floats detached from the viewport edge — card-like, elevated.
    shell = (
      <div className="flex h-screen flex-col overflow-hidden bg-background">
        {mobileNav}
        <div className="flex min-h-0 flex-1 gap-1 overflow-hidden p-3">
          <div className="hidden overflow-hidden rounded-2xl shadow-xl md:block">
            <WideRail props={navProps} appName={appName} />
          </div>
          {main}
        </div>
      </div>
    );
  } else {
    // standard-rail: the classic hover-expand SideNav.
    shell = (
      <div className="flex h-screen overflow-hidden bg-background">
        <SideNav {...navProps} appName={appName} />
        {main}
      </div>
    );
  }

  return (
    <ShellStateProvider>
      {/* AppNavigator makes schema-driven navigation soft AND hosts the routed
          modal overlay: navigations to /[entity]/new, /[entity]/[id], and
          /[entity]/[id]/edit open as a Dialog/Drawer over the current page
          (URL-synced via history) instead of a full-page navigation. */}
      <AppNavigator><div data-skin={identity.skin || undefined} className="contents">{trackerTag}{shell}</div></AppNavigator>
    </ShellStateProvider>
  );
}
