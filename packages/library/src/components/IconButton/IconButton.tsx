"use client";
import { useContext } from "react";
import { WorkflowDispatcherContext } from "@tentoroforge/renderer";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { buttonVariants } from "../Button/variants";
import { looksLikeIconName, resolveIcon } from "../../icons";

type Props = {
  icon?: string;
  /** Image/SVG URL (e.g. a Figma-exported asset) rendered as an <img>. */
  iconSrc?: string;
  "aria-label"?: string;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  loading?: boolean;
  workflow?: string;
  args?: Record<string, unknown>;
  navigate?: string;
  className?: string;
  style?: StyleSlotT;
  /** Test injection only — allows bypassing context in unit tests. */
  __dispatch?: (workflow: string, args?: Record<string, unknown>) => void;
};

// Square size overrides: CVA size classes include px-* for horizontal padding;
// icon buttons must be square so we override with w-*/p-0 instead.
const SQUARE_SIZE: Record<NonNullable<Props["size"]>, string> = {
  sm: "h-8  w-8  p-0",
  md: "h-10 w-10 p-0",
  lg: "h-12 w-12 p-0",
};

const GLYPH_PX: Record<NonNullable<Props["size"]>, number> = { sm: 16, md: 20, lg: 24 };

/**
 * What to show when `icon` is set but names no icon we have.
 *
 * The bug this replaces: the component rendered the raw `icon` STRING, so the
 * registry's default `icon: "Plus"` painted the literal word "Plus" inside the
 * button. Rendering nothing instead would be worse in the editor — an empty
 * square looks like a styling bug rather than a bad prop value — so an
 * unresolved NAME gets a dashed outline plus `data-unresolved-icon`, which
 * reads as "slot with nothing in it" and carries the offending value for the
 * author (and for a test) to see. A non-name string ("✕", "🗑", "→") is a glyph
 * the author typed on purpose and is still rendered verbatim.
 */
function UnresolvedIcon({ name, px }: { name: string; px: number }) {
  return (
    <span
      data-unresolved-icon={name}
      title={`Unknown icon "${name}"`}
      aria-hidden="true"
      style={{
        display: "inline-block",
        width: px,
        height: px,
        borderRadius: 4,
        border: "1px dashed currentColor",
        opacity: 0.5,
      }}
    />
  );
}

export function IconButton({
  icon,
  iconSrc,
  "aria-label": ariaLabel,
  variant = "secondary",
  size = "md",
  disabled,
  loading,
  workflow,
  args,
  navigate,
  className,
  style,
  __dispatch,
}: Props) {
  const ctxDispatch = useContext(WorkflowDispatcherContext);

  const onClick = () => {
    if (disabled || loading) return;
    if (workflow) {
      const dispatch = __dispatch ?? ctxDispatch;
      if (dispatch) dispatch(workflow, args);
    }
    if (navigate) window.location.assign(navigate);
  };

  // Compose CVA base+variant classes then override size padding with square
  // dims. A caller-supplied className (Figma styling) is appended so it can win.
  const cls = `${buttonVariants({ variant, size })} ${SQUARE_SIZE[size ?? "md"]}${className ? ` ${className}` : ""}`;

  // The whole point of the component, and it was missing: `icon` is an icon
  // NAME ("plus", "ChevronDown"), not text. Button.tsx has always resolved it;
  // IconButton interpolated the string straight into the DOM.
  const Icon = icon ? resolveIcon(icon) : null;
  const px = GLYPH_PX[size ?? "md"];

  // `iconSrc` still wins over `icon`: the Figma pipeline emits an exported SVG
  // URL alongside whatever default `icon` the registry filled in, and the
  // exported asset is the one the author drew.
  const content = loading
    ? "…"
    : iconSrc
      ? <img src={iconSrc} alt="" aria-hidden="true" className="w-5 h-5 object-contain" />
      : Icon
        ? <Icon size={px} aria-hidden="true" data-icon={icon} />
        : icon
          ? (looksLikeIconName(icon)
              ? <UnresolvedIcon name={icon} px={px} />
              : <span aria-hidden="true">{icon}</span>)
          : null;

  return (
    <button
      type="button"
      aria-label={ariaLabel ?? "icon button"}
      disabled={disabled}
      aria-busy={loading ? "true" : undefined}
      onClick={onClick}
      className={cls}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {content}
    </button>
  );
}
