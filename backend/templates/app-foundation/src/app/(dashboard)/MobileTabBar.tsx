"use client";
// The bottom tab bar of a mobile-first application — its main destinations
// under the thumb, as a phone app has them. Shown below `md` only; the rail
// (or top bar) stays the navigation above it. Projected from the Blueprint
// (`navigation.mobile`) into shell.json `mobile.tabs`.

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export type Tab = { label: string; route: string; icon: React.ReactNode };

function active(pathname: string, route: string): boolean {
  if (route === "/") return pathname === "/";
  return pathname === route || pathname.startsWith(route + "/");
}

export function MobileTabBar({ tabs }: { tabs: Tab[] }) {
  const pathname = usePathname() || "/";
  return (
    <nav aria-label="Main" data-mobile-tabs=""
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card/95 backdrop-blur md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
      <ul className="mx-auto flex max-w-lg items-stretch justify-around">
        {tabs.map((t) => {
          const on = active(pathname, t.route);
          return (
            <li key={t.route} className="flex-1">
              <Link href={t.route} aria-current={on ? "page" : undefined}
                className={"flex h-16 flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors "
                  + (on ? "text-primary" : "text-muted-foreground hover:text-foreground")}>
                <span className={"grid h-7 w-12 place-items-center rounded-full transition-colors " + (on ? "bg-primary/10" : "")}>
                  {t.icon}
                </span>
                <span className="max-w-full truncate px-1">{t.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
