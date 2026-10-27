"use client";

import { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatsCardProps {
  title: string;
  value: string | number;
  icon: LucideIcon;
  description?: string;
  trend?: { value: number; label: string };
  variant?: "default" | "primary" | "success" | "warning" | "error";
  className?: string;
}

// Status variants use the app's own status tokens (success/warning/destructive
// and their -subtle grounds), not hardcoded Tailwind palette — so they sit in
// the design's palette and work in both light and dark without per-mode classes.
const variantStyles = {
  default: "bg-card",
  primary: "bg-primary/5 border-primary/20",
  success: "bg-success-subtle border-success/25",
  warning: "bg-warning-subtle border-warning/25",
  error: "bg-destructive-subtle border-destructive/25",
};

const iconStyles = {
  default: "bg-muted text-muted-foreground",
  primary: "bg-primary/10 text-primary",
  success: "bg-success/15 text-success",
  warning: "bg-warning/15 text-warning",
  error: "bg-destructive/15 text-destructive",
};

export function StatsCard({ title, value, icon: Icon, description, trend, variant = "default", className }: StatsCardProps) {
  return (
    <div className={cn("rounded-xl border p-5 shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5", variantStyles[variant], className)}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</span>
        <div className={cn("rounded-lg p-2", iconStyles[variant])}>
          <Icon className="h-4 w-4" />
        </div>
      </div>
      <p className="text-2xl font-bold text-foreground">{value}</p>
      {description && <p className="mt-1 text-xs text-muted-foreground">{description}</p>}
      {trend && (
        <p className={cn("mt-1 text-xs", trend.value >= 0 ? "text-success" : "text-destructive")}>
          {trend.value >= 0 ? "↑" : "↓"} {Math.abs(trend.value)}% {trend.label}
        </p>
      )}
    </div>
  );
}
