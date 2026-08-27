"use client";

import { LucideIcon, Inbox } from "lucide-react";
import Link from "next/link";
import { ReactNode } from "react";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description: string | ReactNode;
  action?: ReactNode | { label: string; href?: string; onClick?: () => void; variant?: "default" | "outline" };
  children?: ReactNode;
}

export function EmptyState({ icon: Icon = Inbox, title, description, action, children }: EmptyStateProps) {
  const renderAction = () => {
    if (!action) return null;
    if (typeof action === "object" && "type" in (action as any)) return action as ReactNode;
    const act = action as { label: string; href?: string; onClick?: () => void };
    if (act.href) {
      return (
        <Link href={act.href} className="inline-flex items-center rounded-xl bg-primary text-primary-foreground px-6 py-2.5 text-sm font-medium shadow-sm hover:opacity-90 transition-all">
          {act.label}
        </Link>
      );
    }
    return (
      <button onClick={act.onClick} className="rounded-xl bg-primary text-primary-foreground px-6 py-2.5 text-sm font-medium shadow-sm hover:opacity-90 transition-all">
        {act.label}
      </button>
    );
  };

  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="rounded-full bg-muted/50 p-6 mb-4">
        <Icon className="h-12 w-12 text-muted-foreground" />
      </div>
      <h3 className="text-lg font-semibold text-foreground mb-2">{title}</h3>
      <p className="text-sm text-muted-foreground mb-6 max-w-md mx-auto">{description}</p>
      {renderAction()}
      {children}
    </div>
  );
}
