"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { PresenceIndicatorPropsType } from "./PresenceIndicator.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useIdleRender } from "../../util/designTime";

export type PresenceUser = {
  userId: string;
  name?: string;
  avatarUrl?: string;
  color?: string;
};

export interface PresenceIndicatorProps extends PresenceIndicatorPropsType {
  style?: StyleSlotT;
  /**
   * Optional explicit users list. When omitted, the component
   * subscribes to the runtime `usePresence(route)` hook via a global
   * `window.__forgePresenceHook__` provided by `@forge/renderer` (kept
   * loose to avoid a hard cross-package dep).
   */
  users?: PresenceUser[];
}

function initials(name?: string, fallback = "?"): string {
  if (!name) return fallback;
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("") || fallback;
}

function pickColor(userId: string): string {
  // Deterministic colour from userId — no hash lib needed.
  let h = 0;
  for (const ch of userId) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h} 55% 50%)`;
}

export function PresenceIndicator({
  route,
  max = 5,
  size = 28,
  showTooltips = true,
  style,
  className,
  users: usersProp,
}: PresenceIndicatorProps): React.ReactElement | null {
  const [users, setUsers] = React.useState<PresenceUser[]>(usersProp ?? []);
  // Hook order is fixed regardless of the branch below — the `return null` that
  // used to sit here was above nothing, but the same guard in CartBadge WAS
  // above a hook and changed the hook count with the fetch result.
  const idle = useIdleRender(
    "PresenceIndicator",
    "Nobody here yet — avatars arrive from the live presence stream.",
    200,
  );

  React.useEffect(() => {
    if (usersProp) {
      setUsers(usersProp);
      return;
    }
    if (typeof window === "undefined") return;
    const hook = (window as any).__forgePresenceHook__ as
      | ((r?: string, cb?: (u: PresenceUser[]) => void) => () => void)
      | undefined;
    if (typeof hook !== "function") return;
    return hook(route, (u) => setUsers(u ?? []));
  }, [usersProp, route]);

  // Outside an authoring surface this is exactly the previous `return null`.
  // Inside the editor it is a box the author can see, click and style — the
  // four exposed props (`max`, `size`, `showTooltips`, `route`) were otherwise
  // four controls that provably could not alter anything on screen.
  if (users.length === 0) return idle;
  const visible = users.slice(0, max);
  const overflow = users.length - visible.length;
  const styleProps = resolveStyle(style);

  return (
    <div
      data-forge-presence
      role="group"
      aria-label={`${users.length} user${users.length === 1 ? "" : "s"} on this page`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        ...styleProps,
      }}
      className={className}
    >
      {visible.map((u, i) => {
        const color = u.color ?? pickColor(u.userId);
        const style: React.CSSProperties = {
          width: size,
          height: size,
          borderRadius: "50%",
          background: u.avatarUrl ? `center/cover no-repeat url(${u.avatarUrl})` : color,
          color: "white",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: Math.max(10, Math.round(size * 0.4)),
          fontWeight: 600,
          border: "2px solid var(--background, white)",
          marginLeft: i === 0 ? 0 : -Math.round(size * 0.35),
          boxSizing: "border-box",
        };
        return (
          <span
            key={u.userId}
            style={style}
            title={showTooltips ? u.name ?? u.userId : undefined}
            data-user-id={u.userId}
          >
            {u.avatarUrl ? "" : initials(u.name, u.userId.slice(0, 2).toUpperCase())}
          </span>
        );
      })}
      {overflow > 0 ? (
        <span
          style={{
            width: size,
            height: size,
            borderRadius: "50%",
            background: "var(--muted, hsl(0 0% 92%))",
            color: "var(--muted-foreground, hsl(0 0% 40%))",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: Math.max(10, Math.round(size * 0.38)),
            fontWeight: 600,
            border: "2px solid var(--background, white)",
            marginLeft: -Math.round(size * 0.35),
          }}
          aria-label={`${overflow} more`}
        >
          +{overflow}
        </span>
      ) : null}
    </div>
  );
}
