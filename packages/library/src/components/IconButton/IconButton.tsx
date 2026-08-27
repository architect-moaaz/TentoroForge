"use client";
import { useContext } from "react";
import { WorkflowDispatcherContext } from "@tentoroforge/renderer";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { buttonVariants } from "../Button/variants";

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
      {loading ? "…" : iconSrc
        ? <img src={iconSrc} alt="" aria-hidden="true" className="w-5 h-5 object-contain" />
        : icon}
    </button>
  );
}
