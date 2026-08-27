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

const variantStyles = {
  default: "bg-card",
  primary: "bg-primary/5 border-primary/20",
  success: "bg-emerald-50 border-emerald-200 dark:bg-emerald-900/10 dark:border-emerald-800",
  warning: "bg-amber-50 border-amber-200 dark:bg-amber-900/10 dark:border-amber-800",
  error: "bg-red-50 border-red-200 dark:bg-red-900/10 dark:border-red-800",
};

const iconStyles = {
  default: "bg-muted text-muted-foreground",
  primary: "bg-primary/10 text-primary",
  success: "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400",
  warning: "bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400",
  error: "bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400",
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
        <p className={cn("mt-1 text-xs", trend.value >= 0 ? "text-emerald-600" : "text-red-600")}>
          {trend.value >= 0 ? "↑" : "↓"} {Math.abs(trend.value)}% {trend.label}
        </p>
      )}
    </div>
  );
}
