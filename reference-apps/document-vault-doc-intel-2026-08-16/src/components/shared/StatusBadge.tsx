"use client";

import { cn } from "@/lib/utils";

const variants: Record<string, string> = {
  default: "bg-muted text-muted-foreground",
  success: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  warning: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  error: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  info: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  primary: "bg-primary/10 text-primary",
};

interface StatusBadgeProps {
  status: string;
  variant?: keyof typeof variants | string;
  className?: string;
}

export function StatusBadge({ status, variant = "default", className }: StatusBadgeProps) {
  const style = variants[variant] || variants.default;
  return (
    <span className={cn("inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium", style, className)}>
      {status}
    </span>
  );
}
