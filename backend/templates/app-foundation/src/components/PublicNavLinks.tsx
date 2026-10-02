"use client";
// The public pages' menu links, with the current one marked — the only part
// of the public frame that needs to know where the visitor is.
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { PublicNavItem } from "@/contracts/public-nav";

function isActive(pathname: string, route: string): boolean {
  if (route === "/") return pathname === "/";
  return pathname === route || pathname.startsWith(route + "/");
}

export function PublicNavLinks({ items }: { items: PublicNavItem[] }) {
  const pathname = usePathname() ?? "/";
  // The most specific match wins, so /records/new marks "Add record", not "Records".
  const active = items
    .filter((i) => isActive(pathname, i.route))
    .sort((a, b) => b.route.length - a.route.length)[0]?.route;
  return (
    <nav aria-label="Main" className="-mx-1 flex min-w-0 items-center gap-1 overflow-x-auto">
      {items.map((item) => {
        const current = item.route === active;
        return (
          <Link
            key={item.route}
            href={item.route}
            aria-current={current ? "page" : undefined}
            className={
              "whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors " +
              (current
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground")
            }
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
