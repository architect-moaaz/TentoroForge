"use client";

import { useEffect, useState } from "react";
import { resolveIcon } from "../../icons";
import { useTokens } from "../../theme/tokens-context";
import type { StyleSlotT } from "@tentoroforge/schema";

/**
 * Collapsible, responsive navigation rail.
 *
 *  - Desktop (≥768px): an icon-only strip that expands on hover to reveal main
 *    menu items (icon + label) and indented sub-items (icon + label).
 *  - Mobile (<768px): an off-canvas drawer with a hamburger + backdrop. The
 *    Engine's ShellStateProvider toggles `data-sidebar-open` on an ancestor
 *    (delegated click on `[data-sidebar-toggle]` / `[data-sidebar-backdrop]`,
 *    and auto-close on nav-link clicks inside `[data-shell-sidebar]`).
 *
 * Layout/responsive behavior is driven by a scoped <style> block (Tailwind does
 * not scan classes that live only in shell.json); dynamic colors flow through CSS
 * custom properties so the rail is painted from the design-spec palette. Items
 * navigate via `data-nav-trigger`, which the Engine uses to swap the PageOutlet.
 */

type SubItem = { label: string; route: string; icon?: string };
type Group = { label?: string; icon?: string; route?: string; items?: SubItem[] };

type Props = {
  groups?: Group[];
  appName?: string;
  mode?: "dark" | "light";
  bg?: string;
  text?: string;
  muted?: string;
  accent?: string;
  collapsedWidth?: number;
  expandedWidth?: number;
  style?: StyleSlotT;
};

const DEFAULTS = {
  dark: { bg: "#16233A", text: "#C7D2DE", muted: "#7C8BA0", accent: "#5B8DEF" },
  light: { bg: "#FFFFFF", text: "#334155", muted: "#94A3B8", accent: "#2563EB" },
};

function Glyph({ name, size }: { name?: string; size: number }) {
  // Fall back to a generic glyph so a nav item is never iconless.
  const C = resolveIcon(name) ?? resolveIcon("circle");
  return C ? (
    <C size={size} strokeWidth={2} style={{ minWidth: size, flexShrink: 0 }} />
  ) : (
    <span style={{ minWidth: size, width: size, flexShrink: 0 }} aria-hidden />
  );
}

const CSS = `
.tf-burger{position:fixed;top:12px;left:12px;z-index:60;width:40px;height:40px;border-radius:8px;display:flex;align-items:center;justify-content:center;background:var(--tf-bg);color:var(--tf-text);border:none;cursor:pointer}
.tf-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:40;display:none;border:none}
[data-sidebar-open="true"] .tf-backdrop{display:block}
.tf-sidenav{position:fixed;top:0;left:0;bottom:0;z-index:50;width:var(--tf-we);background:var(--tf-bg);color:var(--tf-text);display:flex;flex-direction:column;overflow:hidden;transform:translateX(-100%);transition:transform .22s ease}
[data-sidebar-open="true"] .tf-sidenav{transform:translateX(0)!important}
.tf-row,.tf-sub{display:flex;align-items:center;gap:14px;padding:9px 20px;cursor:pointer;text-decoration:none;color:var(--tf-text);border-left:3px solid transparent;font-size:0.875rem}
.tf-sub{padding:7px 20px 7px 30px;font-size:0.8125rem;color:var(--tf-muted)}
.tf-row:hover,.tf-sub:hover{background:var(--tf-hover)}
.tf-active{background:var(--tf-abg)!important;color:var(--tf-atext)!important;border-left-color:var(--tf-accent)!important}
.tf-label{opacity:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:opacity .14s ease .03s}
.tf-brand{opacity:1;font-weight:600;overflow:hidden;transition:opacity .14s ease .03s;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;line-clamp:2;overflow-wrap:anywhere;line-height:1.2;font-size:0.875rem}
@media (min-width:768px){.tf-sidenav .tf-brand{opacity:0}.tf-sidenav:hover .tf-brand{opacity:1}}
.tf-subs{max-height:999px;overflow:hidden;transition:max-height .22s ease}
@media (min-width:768px){
.tf-burger,.tf-backdrop{display:none!important}
.tf-sidenav{position:relative;transform:none;z-index:auto;width:var(--tf-wc);flex-shrink:0;transition:width .2s ease}
[data-sidebar-open] .tf-sidenav{transform:none!important}
.tf-sidenav:hover{width:var(--tf-we)}
.tf-sidenav .tf-label{opacity:0}
.tf-sidenav:hover .tf-label{opacity:1}
.tf-sidenav .tf-subs{max-height:0}
.tf-sidenav:hover .tf-subs{max-height:320px}
}`;

export function SideNav({
  groups = [],
  appName = "App",
  mode = "dark",
  bg,
  text,
  muted,
  accent,
  collapsedWidth = 64,
  expandedWidth = 236,
}: Props) {
  // Per-app rail identity: explicit props win, then the app's THEME TOKENS
  // (tokens.color.sidebar — written per project by the design pipeline), then
  // the static defaults. Without the token fallback, every app whose shell
  // carried no colors rendered the identical navy rail regardless of its
  // palette — a major "all generated apps look the same" driver.
  const tokens = useTokens() as { color?: { sidebar?: { bg?: string; text?: string; active?: string } } };
  const tokSidebar = tokens?.color?.sidebar;
  const d = DEFAULTS[mode] ?? DEFAULTS.dark;
  const cBg = bg ?? tokSidebar?.bg ?? d.bg;
  const cText = text ?? tokSidebar?.text ?? d.text;
  const cMuted = muted ?? d.muted;
  const cAccent = accent ?? d.accent;
  // tokens.color.sidebar.active is the ACTIVE-ITEM BACKGROUND (not the accent
  // line) — thread it into --tf-abg below when present.
  const cActiveBg = tokSidebar?.active;
  // Light/dark chrome follows the RESOLVED rail color when it's a hex —
  // a light token rail must get dark hover/active treatment even if the
  // caller left mode at its "dark" default.
  let light = mode === "light";
  if (/^#[0-9a-fA-F]{6}$/.test(cBg)) {
    const r = parseInt(cBg.slice(1, 3), 16), g = parseInt(cBg.slice(3, 5), 16), b = parseInt(cBg.slice(5, 7), 16);
    light = (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6;
  }

  const vars: React.CSSProperties = {
    display: "contents",
    ["--tf-bg" as string]: cBg,
    ["--tf-text" as string]: cText,
    ["--tf-muted" as string]: cMuted,
    ["--tf-accent" as string]: cAccent,
    ["--tf-hover" as string]: light ? "rgba(0,0,0,0.04)" : "rgba(255,255,255,0.05)",
    ["--tf-abg" as string]: cActiveBg ?? (light ? "rgba(0,0,0,0.05)" : "rgba(255,255,255,0.09)"),
    ["--tf-atext" as string]: light ? cAccent : "#fff",
    ["--tf-wc" as string]: `${collapsedWidth}px`,
    ["--tf-we" as string]: `${expandedWidth}px`,
  };
  const divider = light ? "rgba(0,0,0,0.08)" : "rgba(255,255,255,0.07)";

  const [active, setActive] = useState("");
  useEffect(() => {
    const sync = () => setActive(window.location.pathname);
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  const isActive = (route?: string) =>
    !!route && (active === route || (route !== "/" && active.startsWith(route)));

  function leaf(item: SubItem | Group, sub = false) {
    const route = (item as SubItem).route || "";
    const act = isActive(route);
    return (
      <a
        key={`${sub ? "s" : "m"}:${route}:${item.label}`}
        href={route || "#"}
        data-nav-trigger={route || undefined}
        onClick={() => route && setActive(route)}
        data-nav-item=""
        data-active={act ? "true" : "false"}
        className={`${sub ? "tf-sub" : "tf-row"}${act ? " tf-active" : ""}`}
      >
        <span data-nav-icon="" className="inline-flex">
          <Glyph name={item.icon} size={sub ? 17 : 20} />
        </span>
        <span className="tf-label" data-nav-label="">{item.label}</span>
      </a>
    );
  }

  return (
    <div style={vars}>
      <style>{CSS}</style>

      <button className="tf-burger" data-sidebar-toggle aria-label="Open menu">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>
      <div className="tf-backdrop" data-sidebar-backdrop aria-hidden />

      <nav className="tf-sidenav" data-shell-sidebar data-shell-nav="" aria-label="Main navigation">
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            padding: "16px 18px",
            borderBottom: `.5px solid ${divider}`,
          }}
        >
          <span
            style={{
              minWidth: 28,
              height: 28,
              borderRadius: 7,
              background: cAccent,
              color: "#fff",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 600,
              fontSize: 14,
            }}
          >
            {(appName || "A").trim().charAt(0).toUpperCase()}
          </span>
          <span
            className="tf-brand"
            title={appName}
            aria-label={appName}
            style={{ color: light ? "#0F172A" : "#fff" }}
          >
            {appName}
          </span>
        </div>

        <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden", padding: "8px 0" }}>
          {groups.map((g, gi) => {
            const subs = g.items || [];
            if (!subs.length) return leaf(g);
            const sectionActive = subs.some((s) => isActive(s.route)) || isActive(g.route);
            return (
              <div key={`g:${gi}`}>
                <div data-nav-group-label="" className={`tf-row${sectionActive ? " tf-active" : ""}`}>
                  <span data-nav-icon="" className="inline-flex">
                    <Glyph name={g.icon} size={20} />
                  </span>
                  <span className="tf-label" data-nav-label="">{g.label}</span>
                </div>
                <div className="tf-subs">{subs.map((s) => leaf(s, true))}</div>
              </div>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
