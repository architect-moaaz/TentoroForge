"use client";

import { useQuery } from "@tanstack/react-query";
import {
  DollarSign,
  Loader2,
  AlertCircle,
  BarChart3,
  Zap,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import type { ProjectCostSummary, ErrorLogEntry } from "@/types/portal";

interface CostTrackingPanelProps {
  projectId: string;
}

function formatCost(usd: number): string {
  if (usd < 0.01) return "<$0.01";
  return `$${usd.toFixed(2)}`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function CostTrackingPanel({ projectId }: CostTrackingPanelProps) {
  const {
    data: costs,
    isLoading: costsLoading,
    refetch: refetchCosts,
  } = useQuery({
    queryKey: ["project", projectId, "monitoring", "costs"],
    queryFn: () =>
      api.get<ProjectCostSummary>(
        `/api/projects/${projectId}/monitoring/costs`,
      ),
  });

  const {
    data: errorsData,
    isLoading: errorsLoading,
    refetch: refetchErrors,
  } = useQuery({
    queryKey: ["project", projectId, "monitoring", "errors"],
    queryFn: () =>
      api.get<{ errors: ErrorLogEntry[]; total: number }>(
        `/api/projects/${projectId}/monitoring/errors`,
      ),
  });

  const errors = errorsData?.errors ?? [];
  const isLoading = costsLoading || errorsLoading;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Monitoring</h2>
          <p className="text-sm text-muted-foreground">
            Cost tracking and error logs
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            refetchCosts();
            refetchErrors();
          }}
        >
          <RefreshCw className="mr-1 h-3 w-3" />
          Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          {/* Cost summary cards */}
          <div className="grid gap-4 sm:grid-cols-3">
            <Card>
              <CardHeader className="pb-2">
                <CardDescription className="flex items-center gap-1 text-xs">
                  <DollarSign className="h-3 w-3" />
                  Total Cost
                </CardDescription>
                <CardTitle className="text-2xl">
                  {formatCost(costs?.total_cost_usd ?? 0)}
                </CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription className="flex items-center gap-1 text-xs">
                  <Zap className="h-3 w-3" />
                  Input Tokens
                </CardDescription>
                <CardTitle className="text-2xl">
                  {formatTokens(costs?.total_input_tokens ?? 0)}
                </CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription className="flex items-center gap-1 text-xs">
                  <Zap className="h-3 w-3" />
                  Output Tokens
                </CardDescription>
                <CardTitle className="text-2xl">
                  {formatTokens(costs?.total_output_tokens ?? 0)}
                </CardTitle>
              </CardHeader>
            </Card>
          </div>

          {/* Cost by agent */}
          {costs?.by_agent && Object.keys(costs.by_agent).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <BarChart3 className="h-4 w-4" />
                  Cost by Agent
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {Object.entries(costs.by_agent)
                    .sort(([, a], [, b]) => (b.cost_usd || 0) - (a.cost_usd || 0))
                    .map(([agent, data]) => (
                      <div
                        key={agent}
                        className="flex items-center justify-between rounded-md border px-3 py-2"
                      >
                        <div>
                          <span className="text-sm font-medium">{agent}</span>
                          <span className="ml-2 text-xs text-muted-foreground">
                            {data.calls} calls
                          </span>
                        </div>
                        <span className="text-sm font-medium">
                          {formatCost(data.cost_usd || 0)}
                        </span>
                      </div>
                    ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Daily cost chart (simple bar representation) */}
          {costs?.daily && costs.daily.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <BarChart3 className="h-4 w-4" />
                  Daily Usage
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-1">
                  {costs.daily.slice(-14).map((entry) => {
                    const maxCost = Math.max(
                      ...costs.daily.map((d) => d.cost_usd || 0),
                      0.01,
                    );
                    const pct = ((entry.cost_usd || 0) / maxCost) * 100;

                    return (
                      <div key={entry.date} className="flex items-center gap-3">
                        <span className="w-20 shrink-0 text-xs text-muted-foreground">
                          {entry.date.slice(5)}
                        </span>
                        <div className="flex-1">
                          <div
                            className="h-4 rounded-sm bg-primary/20"
                            style={{ width: `${Math.max(pct, 2)}%` }}
                          />
                        </div>
                        <span className="w-16 shrink-0 text-right text-xs">
                          {formatCost(entry.cost_usd || 0)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Error logs */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-sm">
                  <AlertCircle className="h-4 w-4" />
                  Error Logs
                </CardTitle>
                {errors.length > 0 && (
                  <Badge variant="destructive" className="text-[10px]">
                    {errors.length}
                  </Badge>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {errors.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  No errors recorded
                </p>
              ) : (
                <div className="space-y-2">
                  {errors.slice(0, 20).map((err) => (
                    <div
                      key={err.id}
                      className="flex items-start gap-3 rounded-md border p-3"
                    >
                      <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm">{err.message}</p>
                        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                          {err.agent_type && (
                            <Badge variant="outline" className="text-[10px]">
                              {err.agent_type}
                            </Badge>
                          )}
                          <span>{err.type}</span>
                          {err.created_at && (
                            <span>
                              {new Date(err.created_at).toLocaleDateString()}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
