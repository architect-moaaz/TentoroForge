"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity, AppWindow, BarChart3, Building2, ChevronLeft, Coins, LayoutDashboard, LayoutTemplate, LogOut, ShieldCheck, Users, ToggleLeft, Radio } from "lucide-react";
import { NotificationBell } from "@/components/NotificationBell";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { AuthGuard } from "@/components/auth-guard";
import { SuperAdminGate } from "@/components/admin/SuperAdminGate";
import { Badge } from "@/components/ui/badge";
import { useAuthStore } from "@/stores/auth";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  exact?: boolean;
}

const NAV: { label?: string; items: NavItem[] }[] = [
  {
    items: [
      { href: "/admin", label: "Overview", icon: LayoutDashboard, exact: true },
      { href: "/admin/orgs", label: "Organisations", icon: Building2 },
      { href: "/admin/people", label: "People", icon: Users },
      { href: "/admin/live", label: "Live", icon: Radio },
      { href: "/admin/apps", label: "Apps", icon: AppWindow },
      { href: "/admin/templates", label: "Templates", icon: LayoutTemplate },
      { href: "/admin/credits", label: "Credits", icon: Coins },
      { href: "/admin/features", label: "Features", icon: ToggleLeft },
      { href: "/admin/activity", label: "Activity", icon: Activity },
    ],
  },
  {
    label: "DIAGNOSTICS",
    items: [
      { href: "/admin/usage", label: "Usage", icon: BarChart3 },
      { href: "/admin/fidelity-cost", label: "Fidelity cost", icon: BarChart3 },
    ],
  },
];

/** Template requests waiting for review: a Tentoro admin sees them from any cockpit page. */
function PendingTemplates() {
  const { data } = useQuery({
    queryKey: ["template-requests", "count"],
    queryFn: () => api.get<{ pending: number }>("/api/admin/template-requests/count"),
    refetchInterval: 60_000,
  });
  if (!data?.pending) return null;
  return (
    <span
      className="ml-auto rounded-full bg-amber-500 px-1.5 text-[10px] font-semibold leading-4 text-white"
      aria-label={`${data.pending} waiting for review`}
    >
      {data.pending}
    </span>
  );
}

function CockpitShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuthStore();
  return (
    <div className="fixed inset-0 flex overflow-clip bg-slate-50 dark:bg-slate-950">
      <aside className="flex w-[220px] flex-col border-r border-slate-200/80 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-2.5 border-b border-slate-100 px-4 py-4 dark:border-slate-800">
          <Link href="/" className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800">
            <ChevronLeft className="h-4 w-4" />
          </Link>
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1.5 truncate text-sm font-semibold text-slate-900 dark:text-white">
              <ShieldCheck className="h-4 w-4 text-brand-900" /> Platform cockpit
            </p>
            <p className="truncate text-[11px] text-slate-400">every organisation, every app</p>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-3">
          {NAV.map((group, gi) => (
            <div key={gi} className={gi > 0 ? "mt-5" : ""}>
              {group.label && <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-widest text-slate-400">{group.label}</p>}
              <div className="space-y-0.5">
                {group.items.map(({ href, label, icon: Icon, exact }) => {
                  const active = exact ? pathname === href : pathname.startsWith(href);
                  return (
                    <Link key={href} href={href}
                          className={`flex items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-[13px] transition-all ${
                            active ? "bg-brand-900 font-medium text-white shadow-sm"
                                   : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"}`}>
                      <Icon className={`h-[15px] w-[15px] ${active ? "text-white" : "text-slate-400"}`} />
                      {label}
                      {href === "/admin/templates" && <PendingTemplates />}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
        <div className="border-t border-slate-100 px-3 py-3 dark:border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-slate-700 dark:text-slate-300">{user?.email}</p>
              <Badge variant="outline" className="mt-0.5 text-[10px]">Super admin</Badge>
            </div>
            <NotificationBell />
            <button onClick={logout} className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800" title="Sign out">
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <SuperAdminGate>
        <CockpitShell>{children}</CockpitShell>
      </SuperAdminGate>
    </AuthGuard>
  );
}
