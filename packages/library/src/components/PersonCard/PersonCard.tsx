import * as React from "react";
import { z } from "zod";
import type { PersonCardNode } from "@tentoroforge/schema";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useRadiusScale } from "../../theme/tokens-context";

type Props = z.infer<typeof PersonCardNode>["props"];

const STATUS_DOT: Record<string, string> = {
  active:    "bg-emerald-500",
  away:      "bg-amber-500",
  "on-leave": "bg-rose-500",
  offline:   "bg-muted-foreground",
};

const STATUS_LABEL: Record<string, string> = {
  active: "Active",
  away: "Away",
  "on-leave": "On leave",
  offline: "Offline",
};

function getInitials(name: string, fallback?: string): string {
  if (fallback) return fallback;
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function PersonCard({ name, role, department, avatarUrl, avatarInitials, email, status, manager, layout = "compact" }: Props) {
  const initials = getInitials(name, avatarInitials);
  const expanded = layout === "expanded";
  const radiusScale = useRadiusScale();

  return (
    <div className={`flex ${expanded ? `flex-col gap-3 ${RADIUS_SURFACE_CLASS[radiusScale]} border border-border bg-card p-4` : "flex-row items-center gap-3"}`}>
      <div className={`relative flex shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary font-semibold ${expanded ? "h-16 w-16 text-xl" : "h-10 w-10 text-sm"}`}>
        {avatarUrl ? (
          <img src={avatarUrl} alt={name} className="h-full w-full rounded-full object-cover" />
        ) : (
          <span>{initials}</span>
        )}
        {status && (
          <span
            className={`absolute bottom-0 right-0 ${expanded ? "h-4 w-4" : "h-2.5 w-2.5"} rounded-full ring-2 ring-card ${STATUS_DOT[status]}`}
            aria-label={STATUS_LABEL[status]}
          />
        )}
      </div>
      <div className={`min-w-0 flex-1 ${expanded ? "text-center" : ""}`}>
        <p className="font-medium text-sm leading-tight truncate">{name}</p>
        {role && <p className="text-xs text-muted-foreground truncate">{role}</p>}
        {expanded && department && <p className="text-xs text-muted-foreground mt-0.5">{department}</p>}
        {expanded && email && <p className="text-xs text-muted-foreground mt-1 truncate">{email}</p>}
        {expanded && manager && (
          <div className="mt-3 pt-3 border-t border-border w-full">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">Reports to</p>
            {typeof manager === "string" ? (
              <p className="text-xs font-medium">{manager}</p>
            ) : (
              <>
                <p className="text-xs font-medium">{manager.name}</p>
                {manager.role && <p className="text-[11px] text-muted-foreground">{manager.role}</p>}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
