"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AppWindow,
  ClipboardCheck,
  Activity,
  Loader2,
  ExternalLink,
  Search,
  AlertCircle,
  BarChart3,
  Lightbulb,
  Plus,
  Command,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { TaskInbox } from "@/components/portal/TaskInbox";
import { ActivityFeed } from "@/components/portal/ActivityFeed";
import { PortalSearch } from "@/components/portal/PortalSearch";
import { usePortalStore } from "@/stores/portal";
import type {
  PortalDashboardData,
  PortalStatsResponse,
  PortalApp,
} from "@/types/portal";

type PortalTab = "apps" | "tasks" | "activity";

interface PortalDashboardProps {
  orgId: string;
}

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-gray-100 text-gray-700",
  generating: "bg-blue-100 text-blue-700",
  ready: "bg-green-100 text-green-700",
  error: "bg-red-100 text-red-700",
};

function timeAgo(dateStr: string): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function PortalDashboard({ orgId }: PortalDashboardProps) {
  const [tab, setTab] = useState<PortalTab>("apps");
  const [search, setSearch] = useState("");
  const setCommandPaletteOpen = usePortalStore((s) => s.setCommandPaletteOpen);

  const { data, isLoading, error } = useQuery({
    queryKey: ["org", orgId, "portal"],
    queryFn: () =>
      api.get<PortalDashboardData>(`/api/orgs/${orgId}/portal/dashboard`),
  });

  const { data: statsData } = useQuery({
    queryKey: ["org", orgId, "portal", "stats"],
    queryFn: () =>
      api.get<PortalStatsResponse>(`/api/orgs/${orgId}/portal/stats`),
  });

  const apps = data?.apps ?? [];
  const tasks = data?.tasks ?? [];
  const activity = data?.activity ?? [];
  const stats = statsData?.stats;
  const suggestions = statsData?.suggestions ?? [];

  const filteredApps = apps.filter(
    (a) =>
      !search ||
      a.name.toLowerCase().includes(search.toLowerCase()) ||
      a.description?.toLowerCase().includes(search.toLowerCase()),
  );

  const tabs = [
    { id: "apps" as PortalTab, label: "Applications", icon: AppWindow, count: apps.length },
    { id: "tasks" as PortalTab, label: "Pending Tasks", icon: ClipboardCheck, count: tasks.length },
    { id: "activity" as PortalTab, label: "Activity", icon: Activity, count: activity.length },
  ];

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Portal</h1>
          <p className="text-sm text-muted-foreground">
            Access all your applications, tasks, and activity in one place
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="gap-2"
          onClick={() => setCommandPaletteOpen(true)}
        >
          <Search className="h-4 w-4" />
          Search
          <kbd className="pointer-events-none ml-1 inline-flex h-5 items-center gap-0.5 rounded border bg-muted px-1.5 text-[10px] font-medium text-muted-foreground">
            <Command className="h-3 w-3" />K
          </kbd>
        </Button>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardContent className="flex items-center gap-4 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
                <AppWindow className="h-5 w-5 text-blue-700" />
              </div>
              <div>
                <p className="text-2xl font-bold">{stats.total_apps}</p>
                <p className="text-xs text-muted-foreground">Total Apps</p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex items-center gap-4 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
                <BarChart3 className="h-5 w-5 text-green-700" />
              </div>
              <div>
                <p className="text-2xl font-bold">{stats.active_apps}</p>
                <p className="text-xs text-muted-foreground">Active Apps</p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex items-center gap-4 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
                <ClipboardCheck className="h-5 w-5 text-amber-700" />
              </div>
              <div>
                <p className="text-2xl font-bold">{stats.pending_tasks}</p>
                <p className="text-xs text-muted-foreground">Pending Tasks</p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex items-center gap-4 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-100">
                <Activity className="h-5 w-5 text-purple-700" />
              </div>
              <div>
                <p className="text-2xl font-bold">{stats.total_versions}</p>
                <p className="text-xs text-muted-foreground">Total Versions</p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Suggested apps */}
      {suggestions.length > 0 && tab === "apps" && (
        <div className="mb-6">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Lightbulb className="h-4 w-4" />
            Suggested Apps
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {suggestions.map((s) => (
              <Card key={s.department_id} className="border-dashed">
                <CardContent className="flex items-center gap-3 p-4">
                  <div className="flex h-8 w-8 items-center justify-center rounded bg-muted">
                    <Plus className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{s.department_name}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {s.suggestion}
                    </p>
                  </div>
                  <Link href={`/org/${orgId}/projects`}>
                    <Button variant="outline" size="sm">
                      Create
                    </Button>
                  </Link>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div className="mb-6 flex items-center gap-2 border-b pb-2">
        {tabs.map(({ id, label, icon: Icon, count }) => (
          <Button
            key={id}
            variant={tab === id ? "secondary" : "ghost"}
            size="sm"
            className="gap-1.5"
            onClick={() => setTab(id)}
          >
            <Icon className="h-4 w-4" />
            {label}
            {count > 0 && (
              <Badge variant="secondary" className="ml-1 h-5 min-w-[20px] justify-center text-[10px]">
                {count}
              </Badge>
            )}
          </Button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">Loading portal...</span>
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center py-16">
          <AlertCircle className="mb-2 h-8 w-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Could not load portal data</p>
        </div>
      ) : (
        <>
          {/* Apps Grid */}
          {tab === "apps" && (
            <div>
              <div className="mb-4">
                <div className="relative max-w-md">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    className="pl-9"
                    placeholder="Search applications..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
              </div>

              {filteredApps.length === 0 ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16">
                  <AppWindow className="mb-4 h-12 w-12 text-muted-foreground" />
                  <p className="mb-2 text-lg font-medium">No applications yet</p>
                  <p className="mb-4 text-sm text-muted-foreground">
                    Create your first app from the Projects page
                  </p>
                  <Link href={`/org/${orgId}/projects`}>
                    <Button>Go to Projects</Button>
                  </Link>
                </div>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {filteredApps.map((app) => (
                    <AppCard key={app.id} app={app} orgId={orgId} />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Task Inbox — standalone component with its own data fetching */}
          {tab === "tasks" && <TaskInbox orgId={orgId} apps={apps} />}

          {/* Activity Feed — standalone component with its own data fetching */}
          {tab === "activity" && <ActivityFeed orgId={orgId} apps={apps} />}
        </>
      )}

      {/* Command palette (Cmd+K) */}
      <PortalSearch orgId={orgId} />
    </div>
  );
}

function AppCard({ app, orgId }: { app: PortalApp; orgId: string }) {
  const totalBadges =
    app.badges.pending_tasks + app.badges.alerts + app.badges.new_items;

  return (
    <Card className="transition-shadow hover:shadow-md">
      <Link href={`/org/${orgId}/projects/${app.id}`}>
        <CardHeader>
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              <AppWindow className="h-5 w-5 text-muted-foreground" />
              <CardTitle className="text-base">{app.name}</CardTitle>
            </div>
            <Badge
              variant="secondary"
              className={STATUS_COLORS[app.status] || ""}
            >
              {app.status}
            </Badge>
          </div>
          <CardDescription className="line-clamp-2 text-xs">
            {app.description || "No description"}
          </CardDescription>
        </CardHeader>
      </Link>
      <CardContent className="flex items-center justify-between pt-0">
        <div className="flex gap-3 text-xs text-muted-foreground">
          {app.badges.pending_tasks > 0 && (
            <span className="flex items-center gap-1">
              <ClipboardCheck className="h-3 w-3" />
              {app.badges.pending_tasks} tasks
            </span>
          )}
          {app.badges.alerts > 0 && (
            <span className="flex items-center gap-1 text-amber-600">
              <AlertCircle className="h-3 w-3" />
              {app.badges.alerts} alerts
            </span>
          )}
          {app.badges.new_items > 0 && (
            <span className="flex items-center gap-1">
              <Activity className="h-3 w-3" />
              {app.badges.new_items} versions
            </span>
          )}
          {totalBadges === 0 && <span>No activity</span>}
        </div>
        <Link href={`/org/${orgId}/projects/${app.id}`}>
          <Button variant="ghost" size="sm" className="gap-1">
            <ExternalLink className="h-3.5 w-3.5" />
            Open
          </Button>
        </Link>
      </CardContent>
    </Card>
  );
}
