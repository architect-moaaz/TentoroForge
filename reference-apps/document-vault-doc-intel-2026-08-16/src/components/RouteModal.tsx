"use client";
import * as React from "react";

/**
 * A routed overlay rendered by AppNavigator's overlay host. It wraps the child
 * page's schema (create form / edit form / record detail) so `/leases/new` and
 * `/leases/[id]` render as a Drawer / Dialog on top of the still-mounted list
 * instead of a full-page navigation.
 *
 * Chrome is a floating, rounded card (drawer = right-hand sheet, dialog =
 * centered) with a title + optional subtitle header and a subtle close control.
 * Closing (backdrop click, Escape, or ×) calls onClose, which pops the overlay's
 * history entry, revealing the list underneath at its original scroll position.
 */
export function RouteModal({
  variant = "drawer",
  title,
  subtitle,
  onClose,
  children,
}: {
  variant?: "drawer" | "dialog";
  title?: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const close = onClose;

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [close]);

  const isDrawer = variant === "drawer";
  // Floating cards with a small inset from the screen edge — matches the
  // reference's rounded, detached drawer rather than an edge-to-edge sheet.
  const panel = isDrawer
    ? "absolute right-3 top-3 bottom-3 w-[min(30rem,calc(100vw-1.5rem))] animate-in slide-in-from-right-4 fade-in"
    : "absolute left-1/2 top-1/2 w-[min(44rem,calc(100vw-2rem))] max-h-[calc(100dvh-2rem)] -translate-x-1/2 -translate-y-1/2 animate-in zoom-in-95 fade-in";

  return (
    <div
      className="fixed inset-0 z-50"
      role="dialog"
      aria-modal="true"
      aria-label={title || "Details"}
    >
      <div
        className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm"
        onClick={close}
        aria-hidden="true"
      />
      <div
        className={`flex flex-col overflow-hidden rounded-2xl border border-border bg-background shadow-[0_24px_60px_-15px_rgba(2,6,23,0.35)] ${panel}`}
      >
        <header className="flex items-start justify-between gap-3 px-5 pt-4 pb-3">
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-semibold leading-6 text-foreground">
              {title || "Details"}
            </h2>
            {subtitle && (
              <p className="mt-0.5 truncate text-[13px] text-muted-foreground">{subtitle}</p>
            )}
          </div>
          <div className="flex shrink-0 items-center rounded-lg border border-border bg-muted/40 p-0.5">
            <button
              type="button"
              onClick={close}
              aria-label="Close"
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </header>

        {/* dotted section divider, inset from the edges */}
        <div className="mx-5 border-t border-dashed border-border/80" />

        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
}
