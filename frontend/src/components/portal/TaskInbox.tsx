"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ClipboardCheck,
  Clock,
  ExternalLink,
  Filter,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  PortalTask,
  PortalTasksResponse,
  PortalApp,
} from "@/types/portal";

interface TaskInboxProps {
  orgId: string;
  /** Pre-loaded app list for the filter dropdown */
  apps?: PortalApp[];
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

const STATUS_BADGE: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  claimed: "bg-blue-100 text-blue-700",
  completed: "bg-green-100 text-green-700",
  expired: "bg-gray-100 text-gray-700",
  escalated: "bg-red-100 text-red-700",
};

export function TaskInbox({ orgId, apps = [] }: TaskInboxProps) {
  const [appFilter, setAppFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const { data, isLoading, error } = useQuery({
    queryKey: [
      "org",
      orgId,
      "portal",
      "tasks",
      appFilter,
      statusFilter,
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      if (appFilter !== "all") params.set("app_id", appFilter);
      if (statusFilter !== "all") params.set("status", statusFilter);
      return api.get<PortalTasksResponse>(
        `/api/orgs/${orgId}/portal/tasks?${params.toString()}`
      );
    },
    refetchInterval: 30000,
  });

  const tasks = data?.tasks ?? [];

  return (
    <div className="space-y-4">
      {/* Filters */}
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

        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-[150px]">
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="completed">Completed</SelectItem>
            <SelectItem value="failed">Failed</SelectItem>
          </SelectContent>
        </Select>

        {tasks.length > 0 && (
          <Badge variant="secondary" className="ml-auto">
            {tasks.length} task{tasks.length !== 1 ? "s" : ""}
          </Badge>
        )}
      </div>

      {/* Task list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">
            Loading tasks...
          </span>
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center py-12">
          <AlertCircle className="mb-2 h-6 w-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Could not load tasks
          </p>
        </div>
      ) : tasks.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16">
          <ClipboardCheck className="mb-4 h-12 w-12 text-muted-foreground" />
          <p className="text-lg font-medium">All caught up!</p>
          <p className="text-sm text-muted-foreground">
            No pending tasks across your applications
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {tasks.map((task) => (
            <TaskRow key={task.id} task={task} orgId={orgId} />
          ))}
        </div>
      )}
    </div>
  );
}

function TaskRow({ task, orgId }: { task: PortalTask; orgId: string }) {
  return (
    <Link href={`/org/${orgId}/projects/${task.app_id}`}>
      <div className="flex items-center gap-4 rounded-lg border p-4 transition-colors hover:bg-muted/30">
        <ClipboardCheck className="h-5 w-5 shrink-0 text-amber-500" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{task.title}</p>
          <p className="truncate text-xs text-muted-foreground">
            {task.app_name}
            {task.description ? ` - ${task.description}` : ""}
          </p>
        </div>
        {task.created_at && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" />
            {timeAgo(task.created_at)}
          </span>
        )}
        <Badge
          variant="secondary"
          className={`text-[10px] ${STATUS_BADGE[task.status] || ""}`}
        >
          {task.status}
        </Badge>
        <ExternalLink className="h-4 w-4 shrink-0 text-muted-foreground" />
      </div>
    </Link>
  );
}
