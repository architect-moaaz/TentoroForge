"use client";

/**
 * How a feature the organisation lacks looks: still there, locked, with the
 * note saying who can open it. `LockedPanel` stands in for a tab's content;
 * `LockBadge` sits beside a nav item or a tab; `whenLocked` is the click
 * that explains instead of acting.
 */
import { Lock } from "lucide-react";
import { toast } from "sonner";
import { lockedNote } from "@/lib/features";

export function LockBadge({ className = "" }: { className?: string }) {
  return <Lock aria-label="Locked" className={`h-3 w-3 text-amber-500 ${className}`} />;
}

export function explainLock(name: string) {
  toast.info(lockedNote(name));
}

export function LockedPanel({ name, description }: { name: string; description?: string }) {
  return (
    <div className="flex h-full items-center justify-center p-8" data-testid="locked-panel">
      <div className="max-w-md rounded-xl border border-amber-200 bg-amber-50 p-6 text-center dark:border-amber-900 dark:bg-amber-950/40">
        <Lock className="mx-auto mb-3 h-6 w-6 text-amber-500" />
        <h2 className="text-base font-semibold">{name} is locked</h2>
        <p className="mt-1 text-sm text-muted-foreground">{lockedNote(name)}</p>
        {description && <p className="mt-2 text-xs text-muted-foreground">{description}</p>}
      </div>
    </div>
  );
}
