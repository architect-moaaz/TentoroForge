"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Filter,
  Loader2,
  AlertCircle,
  CheckCircle2,
  AlertTriangle,
  FileCode2,
  Workflow,
} from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  PortalActivity,
  PortalActivityResponse,
  PortalApp,
} from "@/types/portal";

interface ActivityFeedProps {
  orgId: string;
  apps?: PortalApp[];
  /** Polling interval in ms (default 30s) */
  pollInterval?: number;
}

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

const TYPE_CONFIG: Record<
  string,
  { icon: typeof Activity; color: string; label: string }
> = {
  task_completed: {
    icon: CheckCircle2,
    color: "text-green-600",
    label: "Completed",
  },
  task_created: {
    icon: Activity,
    color: "text-blue-600",
    label: "Created",
  },
  alert: {
    icon: AlertTriangle,
    color: "text-amber-600",
    label: "Alert",
  },
  workflow_event: {
    icon: Workflow,
    color: "text-purple-600",
    label: "Workflow",
  },
  data_change: {
    icon: FileCode2,
    color: "text-gray-600",
    label: "Update",
  },
};

export function ActivityFeed({
  orgId,
  apps = [],
  pollInterval = 30000,
}: ActivityFeedProps) {
  const [appFilter, setAppFilter] = useState<string>("all");

  const { data, isLoading, error } = useQuery({
    queryKey: ["org", orgId, "portal", "activity", appFilter],
    queryFn: () => {
      const params = new URLSearchParams();
      if (appFilter !== "all") params.set("app_id", appFilter);
      params.set("limit", "50");
      return api.get<PortalActivityResponse>(
        `/api/orgs/${orgId}/portal/activity?${params.toString()}`
      );
    },
    refetchInterval: pollInterval,
  });

  const activity = data?.activity ?? [];

  return (
    <div className="space-y-4">
      {/* Filter */}
      <div className="flex items-center gap-3">
        <Filter className="h-4 w-4 text-muted-foreground" />
        <Select value={appFilter} onValueChange={setAppFilter}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="All apps" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All apps</SelectItem>
            {apps.map((app) => (
              <SelectItem key={app.id} value={app.id}>
                {app.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {activity.length > 0 && (
          <Badge variant="secondary" className="ml-auto">
            {activity.length} event{activity.length !== 1 ? "s" : ""}
          </Badge>
        )}
      </div>

      {/* Activity list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">
            Loading activity...
          </span>
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center py-12">
          <AlertCircle className="mb-2 h-6 w-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Could not load activity
          </p>
        </div>
      ) : activity.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16">
          <Activity className="mb-4 h-12 w-12 text-muted-foreground" />
          <p className="text-lg font-medium">No recent activity</p>
          <p className="text-sm text-muted-foreground">
            Activity from your apps will appear here
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {activity.map((item) => (
            <ActivityRow key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

function ActivityRow({ item }: { item: PortalActivity }) {
  const config = TYPE_CONFIG[item.type] || TYPE_CONFIG.data_change;
  const Icon = config.icon;

  return (
    <div className="flex items-center gap-4 rounded-lg border p-4">
      <Icon className={`h-4 w-4 shrink-0 ${config.color}`} />
      <div className="min-w-0 flex-1">
        <p className="text-sm">{item.title}</p>
        <p className="text-xs text-muted-foreground">
          {item.app_name}
          {item.actor_name ? ` - ${item.actor_name}` : ""}
        </p>
      </div>
      <Badge variant="outline" className="text-[10px]">
        {config.label}
      </Badge>
      <span className="shrink-0 text-xs text-muted-foreground">
        {timeAgo(item.created_at)}
      </span>
    </div>
  );
}
