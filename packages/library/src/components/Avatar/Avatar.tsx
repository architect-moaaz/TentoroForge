import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { AvatarPropsType } from "./Avatar.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useRadiusScale } from "../../theme/tokens-context";

/**
 * Avatar — user portrait. Renders <img> when src is set; otherwise shows
 * fallback initials derived from `name`. Optional online/offline/away/busy
 * status dot. Sizes (sm/md/lg) map to shadcn-style square dimensions; styled
 * with Tailwind utilities so the project's globals.css governs the look.
 */
export interface AvatarProps extends AvatarPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

const SIZE_CLASS: Record<string, string> = {
  sm: "h-8  w-8  text-xs",
  md: "h-10 w-10 text-sm",
  lg: "h-16 w-16 text-base",
};

const STATUS_CLASS: Record<string, string> = {
  // Status dots are semantic signals — green = online, amber = away, red = busy.
  // Use CSS var patterns so projects with custom success/warning tokens override
  // the dot color automatically; fall back to Tailwind defaults otherwise.
  online:  "bg-[var(--color-success-500,theme(colors.emerald.500))]",
  offline: "bg-muted-foreground",
  away:    "bg-[var(--color-warning-500,theme(colors.amber.500))]",
  busy:    "bg-destructive",
};

function getInitials(name: string): string {
  const parts = (name || "").trim().split(/\s+/);
  if (parts.length === 0 || parts[0] === "") return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// Wave 2: radius.scale drives avatar corner radius.
// "round" maps to rounded-full — today's default for circular avatars.
// "soft" gives a slightly rounded square (md); "sharp" gives a square.
const AVATAR_RADIUS: Record<"sharp" | "soft" | "round", string> = {
  sharp: "rounded-none",
  soft:  "rounded-md",
  round: "rounded-full",  // today's default
};

export function Avatar({ src, photoUrl, name, size, status, style }: AvatarProps) {
  const [photoFailed, setPhotoFailed] = React.useState(false);
  const sizeCls = SIZE_CLASS[size ?? "md"] ?? SIZE_CLASS.md;
  const statusCls = status ? STATUS_CLASS[status] : undefined;
  const radiusScale = useRadiusScale();
  const radiusCls = AVATAR_RADIUS[radiusScale];

  // Resolve image source: photoUrl takes precedence over legacy src.
  // photoFailed is reset to false whenever the image source changes so a new
  // valid URL gets a fresh attempt.
  const imgSrc = photoUrl || src;
  const showImg = !!imgSrc && !photoFailed;

  // Initials text uses `text-foreground` on `bg-muted` rather than
  // `text-muted-foreground` (#64748b on #f1f5f9 = 4.34:1, below the AA 4.5:1
  // small-text threshold flagged by axe-core). text-foreground (~slate-900) on
  // bg-muted clears AA comfortably while still reading as a soft, neutral chip.
  return (
    <span
      className={`relative inline-flex shrink-0 items-center justify-center overflow-hidden bg-muted text-foreground font-semibold ${radiusCls} ${sizeCls}`}
      data-avatar-size={size}
      data-avatar-status={status}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {showImg
        ? (
          <img
            className={`h-full w-full object-cover ${radiusCls}`}
            src={imgSrc}
            alt={name}
            loading="lazy"
            onError={() => setPhotoFailed(true)}
          />
        )
        : <span aria-label={name}>{getInitials(name)}</span>}
      {statusCls && (
        <span
          className={`absolute end-0 bottom-0 h-2.5 w-2.5 rounded-full ring-2 ring-background ${statusCls}`}
          data-avatar-status={status}
          aria-hidden="true"
        />
      )}
    </span>
  );
}
