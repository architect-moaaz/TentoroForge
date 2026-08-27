"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Menu, X } from "lucide-react";

type Item = { label: string; route: string };

/**
 * Mobile navigation for the rail chromes (wide-rail / icon-rail / right-rail /
 * floating-rail). Those rails are `hidden md:flex`, so below 768px they vanish
 * with no way to navigate — the app looked like it had "no menu". This adds a
 * top bar + slide-in drawer, shown ONLY below md (md:hidden), so it complements
 * the desktop rail without touching it. Every rail chrome now has working
 * navigation at every viewport width.
 */
export function MobileNav({
  appName,
  items,
  bg,
  text,
}: {
  appName: string;
  items: Item[];
  bg?: string;
  text?: string;
}) {
  const [open, setOpen] = useState(false);

  // Close the drawer on any navigation (soft nav included).
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("popstate", close);
    // lock body scroll while open
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("popstate", close);
      document.body.style.overflow = prev;
    };
  }, [open]);

  const barBg = bg || "hsl(var(--card))";
  const fg = text || "hsl(var(--foreground))";

  return (
    <>
      {/* Top bar — mobile only */}
      <header
        className="md:hidden sticky top-0 z-50 flex h-14 shrink-0 items-center justify-between border-b border-black/10 px-4"
        style={{ background: barBg, color: fg }}
      >
        <span className="truncate text-[15px] font-semibold tracking-tight">{appName}</span>
        <button
          type="button"
          aria-label="Open menu"
          onClick={() => setOpen(true)}
          className="inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-white/10"
        >
          <Menu size={22} />
        </button>
      </header>

      {/* Drawer */}
      {open && (
        <div className="md:hidden fixed inset-0 z-[60]" role="dialog" aria-modal="true">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <nav
            data-shell-nav=""
            className="absolute left-0 top-0 flex h-full w-[82%] max-w-xs flex-col overflow-y-auto p-3 shadow-2xl"
            style={{ background: barBg, color: fg }}
          >
            <div className="mb-3 flex items-center justify-between px-1">
              <span className="truncate text-[15px] font-semibold tracking-tight">{appName}</span>
              <button
                type="button"
                aria-label="Close menu"
                onClick={() => setOpen(false)}
                className="inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-white/10"
              >
                <X size={20} />
              </button>
            </div>
            <ul className="flex flex-col gap-0.5">
              {items.map((it) => (
                <li key={it.route}>
                  <Link
                    href={it.route}
                    data-nav-item=""
                    onClick={() => setOpen(false)}
                    className="flex items-center rounded-md px-3 py-2.5 text-sm hover:bg-white/10"
                  >
                    <span data-nav-label="">{it.label}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      )}
    </>
  );
}
