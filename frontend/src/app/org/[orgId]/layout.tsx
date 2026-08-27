"use client";

import { use } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Users,
  Building2,
  Network,
  Shield,
  UsersRound,
  Settings,
  ChevronLeft,
  Upload,
  FolderOpen,
  LayoutTemplate,
  Sparkles,
  Globe,
  LogOut,
} from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { useAuthStore } from "@/stores/auth";
import { api } from "@/lib/api";

interface Org {
  id: string;
  name: string;
  slug: string;
}

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  /** When true, href is used as-is (not org-prefixed). Used for top-level
   *  routes like /editor that aren't scoped to an org. */
  external?: boolean;
}

interface NavGroup {
  label?: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    items: [
      { href: "", label: "Dashboard", icon: LayoutDashboard },
      { href: "/portal", label: "Portal", icon: Globe },
    ],
  },
  {
    label: "BUILD",
    items: [
      { href: "/projects", label: "Projects", icon: FolderOpen },
      { href: "/discover", label: "Discover", icon: Sparkles },
      { href: "/templates", label: "Templates", icon: LayoutTemplate },
    ],
  },
  {
    label: "ORGANIZATION",
    items: [
      { href: "/people", label: "People", icon: Users },
      { href: "/departments", label: "Departments", icon: Building2 },
      { href: "/teams", label: "Teams", icon: UsersRound },
      { href: "/org-chart", label: "Org Chart", icon: Network },
      { href: "/roles", label: "Roles", icon: Shield },
      { href: "/groups", label: "Groups", icon: UsersRound },
    ],
  },
  {
    items: [
      { href: "/import", label: "Import", icon: Upload },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

function OrgLayout({
  children,
  orgId,
}: {
  children: React.ReactNode;
  orgId: string;
}) {
  const pathname = usePathname();
  const { user, logout } = useAuthStore();

  const { data: org } = useQuery({
    queryKey: ["org", orgId],
    queryFn: () => api.get<Org>(`/api/orgs/${orgId}`),
  });

  const initials = user?.email
    ? user.email.charAt(0).toUpperCase()
    : "?";

  return (
    <div className="flex h-screen bg-slate-50 dark:bg-slate-950">
      {/* Sidebar */}
      <aside className="flex w-[220px] flex-col bg-white border-r border-slate-200/80 dark:bg-slate-900 dark:border-slate-800">
        {/* Org header */}
        <div className="flex items-center gap-2.5 px-4 py-4 border-b border-slate-100 dark:border-slate-800">
          <Link
            href="/"
            className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors dark:hover:bg-slate-800"
          >
            <ChevronLeft className="h-4 w-4" />
          </Link>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">
              {org?.name || "..."}
            </p>
            <p className="truncate text-[11px] text-slate-400">
              /{org?.slug}
            </p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto px-3 py-3">
          {NAV_GROUPS.map((group, gi) => (
            <div key={gi} className={gi > 0 ? "mt-5" : ""}>
              {group.label && (
                <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
                  {group.label}
                </p>
              )}
              <div className="space-y-0.5">
                {group.items.map(({ href, label, icon: Icon, external }) => {
                  const fullHref = external ? href : `/org/${orgId}${href}`;
                  const isActive =
                    href === ""
                      ? pathname === fullHref
                      : pathname.startsWith(fullHref);

                  return (
                    <Link
                      key={href}
                      href={fullHref}
                      className={`flex items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-[13px] transition-all duration-150 ${
                        isActive
                          ? "bg-brand-900 text-white font-medium shadow-sm"
                          : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
                      }`}
                    >
                      <Icon className={`h-[15px] w-[15px] ${isActive ? "text-white" : "text-slate-400"}`} />
                      {label}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* User footer */}
        <div className="border-t border-slate-100 px-3 py-3 dark:border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {initials}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-slate-700 dark:text-slate-300">
                {user?.email?.split("@")[0]}
              </p>
              <p className="truncate text-[10px] text-slate-400">
                {user?.email}
              </p>
            </div>
            <button
              onClick={logout}
              className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors dark:hover:bg-slate-800"
              title="Sign out"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}

export default function OrgLayoutWrapper({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return (
    <AuthGuard>
      <OrgLayout orgId={orgId}>{children}</OrgLayout>
    </AuthGuard>
  );
}
