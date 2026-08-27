"use client";

/**
 * Shared shell for /org/[orgId]/settings/*. Renders a horizontal tab bar
 * at the top; each child route is a separate URL (so deep-linking works
 * and the browser back button behaves like every other page).
 *
 * Adding a new tab: append an entry to TABS and drop a page.tsx at that
 * route.
 */

import { use } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, Building2, KeyRound, Server } from "lucide-react";
import { useIsOrgAdmin } from "@/lib/org-admin";

interface Tab {
  href: string;              // relative to /org/[orgId]/settings
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const TABS: Tab[] = [
  { href: "",              label: "General",      icon: Building2 },
  { href: "/integrations", label: "Integrations", icon: KeyRound },
  { href: "/mcp-servers",  label: "MCP Servers",  icon: Server },
  // Usage & Cost is admin-only — filtered out of the bar for members
  // below (the backend gates the API regardless).
  { href: "/usage",        label: "Usage & Cost", icon: BarChart3 },
];

export default function SettingsLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  const pathname = usePathname();
  const base = `/org/${orgId}/settings`;
  const isAdmin = useIsOrgAdmin(orgId);
  const tabs = TABS.filter((t) => t.href !== "/usage" || isAdmin);

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950">
        <div className="flex items-end px-8 pt-6 gap-1">
          {tabs.map((t) => {
            const href = `${base}${t.href}`;
            const active =
              t.href === ""
                ? pathname === base || pathname === `${base}/`
                : pathname.startsWith(href);
            const Icon = t.icon;
            return (
              <Link
                key={t.href}
                href={href}
                className={[
                  "px-4 py-2.5 -mb-px border-b-2 flex items-center gap-2 text-sm font-medium transition-colors",
                  active
                    ? "border-slate-900 text-slate-900 dark:border-white dark:text-white"
                    : "border-transparent text-slate-500 hover:text-slate-900 hover:border-slate-300 dark:text-slate-400 dark:hover:text-slate-100 dark:hover:border-slate-700",
                ].join(" ")}
              >
                <Icon className="w-4 h-4" />
                {t.label}
              </Link>
            );
          })}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-auto">{children}</div>
    </div>
  );
}
