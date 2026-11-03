"use client";
// The design's frame on every screen size, in every language.
//
// A drawing is made at one width: the DITANS sidebar is 248px wide and every
// page beside it is laid out for a 1440px desktop, so on a laptop half-width
// window or a phone the sidebar kept its 248px and the page was squeezed into
// what was left, titles cut and tiles one word wide (wzml1sa6, 2026-10-31).
// Below 1024px the drawn sidebar is a drawer: a bar with the menu button and
// the application's name sits above the page, and the sidebar slides over it.
// How the page itself gives way is `DrawnFrame.css`.
import * as React from "react";
import { usePathname } from "next/navigation";
import { DrawnWords } from "@/sdk/i18n";
import "./DrawnFrame.css";

export function DrawnFrame({ appName, children }: { appName?: string; children?: React.ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = React.useState(false);
  // Choosing a page closes the drawer.
  React.useEffect(() => setOpen(false), [path]);
  React.useEffect(() => {
    if (!open) return;
    const close = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open]);
  return (
    <div data-drawn-frame="" data-open={open ? "true" : "false"}>
      <DrawnWords />
      <div data-drawn-bar="">
        <button type="button" aria-label="Menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
        </button>
        {appName ? <span>{appName}</span> : null}
      </div>
      <div data-drawn-scrim="" aria-hidden="true" onClick={() => setOpen(false)} />
      <div data-drawn-view="">{children}</div>
    </div>
  );
}
