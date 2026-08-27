import * as React from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

// Auto-generated design-system contract (deterministic). Page shells that every
// page can wrap with, plus small column-renderer helpers. Styled with semantic
// Tailwind tokens (bg-card, text-foreground, text-page-title, ...) defined in
// src/app/globals.css from design-spec.json.

export function ListPageShell({
  title, description, actions, children,
}: {
  title: string; description?: string; actions?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-page-title font-bold text-foreground">{title}</h1>
          {description ? <p className="text-body text-muted-foreground mt-1">{description}</p> : null}
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </div>
  );
}

export function DetailPageShell({
  title, backHref = "..", actions, children,
}: {
  title: string; backHref?: string; actions?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="space-y-6">
      <Link href={backHref} className="inline-flex items-center gap-1 text-body text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Back
      </Link>
      <div className="flex items-start justify-between gap-4">
        <h1 className="text-page-title font-bold text-foreground">{title}</h1>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </div>
  );
}

export function FormPageShell({
  title, backHref = "..", children,
}: {
  title: string; backHref?: string; children: React.ReactNode;
}) {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Link href={backHref} className="inline-flex items-center gap-1 text-body text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Back
      </Link>
      <h1 className="text-page-title font-bold text-foreground">{title}</h1>
      {children}
    </div>
  );
}

export function DashboardShell({
  title, children,
}: {
  title: string; children: React.ReactNode;
}) {
  return (
    <div className="space-y-6">
      <h1 className="text-page-title font-bold text-foreground">{title}</h1>
      {children}
    </div>
  );
}

export function StatusBadge({ status }: { status?: string | null }) {
  return (
    <span className="inline-flex items-center rounded-full bg-secondary px-2.5 py-0.5 text-micro font-medium text-secondary-foreground">
      {status || "—"}
    </span>
  );
}

export function DateCell({ value }: { value?: string | Date | null }) {
  if (!value) return <span className="text-muted-foreground">—</span>;
  const d = typeof value === "string" ? new Date(value) : value;
  return <span className="text-body tabular-nums">{isNaN(d.getTime()) ? "—" : d.toLocaleDateString()}</span>;
}

export function UserAvatar({ name }: { name?: string | null }) {
  const initials = (name || "?").split(" ").filter(Boolean).map((s) => s[0]).slice(0, 2).join("").toUpperCase();
  return (
    <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-micro font-semibold text-primary">
      {initials || "?"}
    </span>
  );
}

export function ActionDropdown({ children }: { children?: React.ReactNode }) {
  return <div className="inline-flex items-center gap-1">{children}</div>;
}
