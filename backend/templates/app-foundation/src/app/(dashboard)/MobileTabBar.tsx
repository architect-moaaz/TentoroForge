"use client";
// The bottom tab bar of a mobile-first application — its main destinations
// under the thumb, as a phone app has them. Shown below `md` only; the rail
// (or top bar) stays the navigation above it. Projected from the Blueprint
// (`navigation.mobile`) into shell.json `mobile.tabs`.

import * as React from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

export type Tab = { label: string; route: string; icon: React.ReactNode };

function active(here: string, route: string, exact: boolean): boolean {
  // A view of a page (`/tools?view=mine`) is lit only on its own address.
  if (exact) return here === route;
  const path = here.split("?")[0];
  if (route.includes("?")) return false;
  if (route === "/") return path === "/";
  return path === route || path.startsWith(route + "/");
}

export function MobileTabBar({ tabs }: { tabs: Tab[] }) {
  const pathname = usePathname() || "/";
  const search = useSearchParams()?.toString() ?? "";
  const here = pathname + (search ? `?${search}` : "");
  const exact = tabs.some((t) => t.route === here);
  return (
    <nav aria-label="Main" data-mobile-tabs=""
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card/95 backdrop-blur md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
      <ul className="mx-auto flex max-w-lg items-stretch justify-around">
        {tabs.map((t) => {
          const on = active(here, t.route, exact);
          return (
            <li key={`${t.route}:${t.label}`} className="flex-1">
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
