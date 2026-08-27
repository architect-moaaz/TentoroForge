"use client";
import * as React from "react";

/**
 * ShellStateContext — engine-level open/close state for the app shell's
 * mobile sidebar drawer.
 *
 * The page-shell heuristic marks the sidebar container with
 * `data-shell-sidebar=""` and the hamburger button with
 * `data-sidebar-toggle=""`. The provider mounts a delegated click handler
 * that toggles `isSidebarOpen` on `data-sidebar-toggle` clicks. The
 * provider's root div sets `data-sidebar-open={isOpen}` so CSS can use
 * `[data-sidebar-open="true"] [data-shell-sidebar]` to slide the sidebar
 * into view on mobile, and a `[data-sidebar-backdrop]` overlay can show.
 *
 * Auto-close behaviours:
 *   - clicking the backdrop closes
 *   - clicking any link / nav-trigger inside the sidebar closes
 *   - pressing Escape closes
 *   - resizing to ≥ md viewport closes (no need for the drawer state then)
 *
 * Lives in @tentoroforge/renderer for the same reason as DialogState:
 * the library imports renderer, engine imports library, so renderer is
 * the only common location without creating a cycle.
 */
export type ShellState = {
  isSidebarOpen: boolean;
  openSidebar: () => void;
  closeSidebar: () => void;
  toggleSidebar: () => void;
};

export const ShellStateContext = React.createContext<ShellState | null>(null);

export function useShellState(): ShellState | null {
  return React.useContext(ShellStateContext);
}

const MD_BREAKPOINT_PX = 768;

export function ShellStateProvider({ children }: { children: React.ReactNode }) {
  const [isSidebarOpen, setOpen] = React.useState(false);
  const rootRef = React.useRef<HTMLDivElement>(null);

  const openSidebar = React.useCallback(() => setOpen(true), []);
  const closeSidebar = React.useCallback(() => setOpen(false), []);
  const toggleSidebar = React.useCallback(() => setOpen((prev) => !prev), []);

  // Delegated click listener — finds `data-sidebar-toggle` or
  // `data-sidebar-backdrop` ancestors so any button/element with those
  // attributes triggers the right action without each one needing its
  // own React handler wired up.
  React.useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      const toggle = target.closest("[data-sidebar-toggle]") as HTMLElement | null;
      if (toggle) {
        e.preventDefault();
        setOpen((prev) => !prev);
        return;
      }
      const backdrop = target.closest("[data-sidebar-backdrop]") as HTMLElement | null;
      if (backdrop) {
        e.preventDefault();
        setOpen(false);
        return;
      }
      // Nav links inside the sidebar should auto-close the drawer so the
      // page transition isn't hidden behind the sidebar.
      const sidebar = target.closest("[data-shell-sidebar]") as HTMLElement | null;
      if (sidebar) {
        const link = target.closest("a, [data-nav-trigger]") as HTMLElement | null;
        if (link) setOpen(false);
      }
    };
    el.addEventListener("click", handler);
    return () => el.removeEventListener("click", handler);
  }, []);

  // Escape closes the drawer.
  React.useEffect(() => {
    if (!isSidebarOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isSidebarOpen]);

  // Resizing to desktop hides the drawer state — keeps the data-sidebar-open
  // flag from sticking around when the breakpoint flips. (The sidebar is
  // always visible on md+ via CSS so the state being true would be a no-op
  // on desktop, but keeping it false avoids surprises if a user resizes
  // back down.)
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const mql = window.matchMedia(`(min-width: ${MD_BREAKPOINT_PX}px)`);
    const onChange = (e: MediaQueryListEvent) => { if (e.matches) setOpen(false); };
    // Some older Safari versions only support addListener / removeListener
    if (mql.addEventListener) mql.addEventListener("change", onChange);
    else mql.addListener(onChange);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener("change", onChange);
      else mql.removeListener(onChange);
    };
  }, []);

  const value = React.useMemo<ShellState>(
    () => ({ isSidebarOpen, openSidebar, closeSidebar, toggleSidebar }),
    [isSidebarOpen, openSidebar, closeSidebar, toggleSidebar],
  );

  return (
    <ShellStateContext.Provider value={value}>
      <div ref={rootRef} data-sidebar-open={isSidebarOpen ? "true" : "false"}>
        {children}
      </div>
    </ShellStateContext.Provider>
  );
}
