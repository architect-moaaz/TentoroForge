"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { AddToCartPropsType } from "./AddToCart.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface AddToCartProps extends AddToCartPropsType {
  style?: StyleSlotT;
  onAdded?: () => void;
}

const VARIANT_CLASS: Record<string, string> = {
  primary: "bg-primary text-primary-foreground hover:opacity-90",
  secondary: "bg-secondary text-secondary-foreground hover:opacity-90",
  outline: "border border-input bg-transparent text-foreground hover:bg-accent",
  ghost: "bg-transparent text-foreground hover:bg-accent",
};

const SIZE_CLASS: Record<string, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-9 px-4 text-sm",
  lg: "h-11 px-5 text-base",
};

/**
 * Renders a button that adds the referenced item to the current user's cart via
 * POST /api/cart. Pending state while the request is in flight; success flashes
 * "Added" for a moment; failure flashes "Failed". Requires an authenticated
 * session — 401s degrade to a "Sign in" hint.
 */
export function AddToCart({
  entity,
  itemId,
  quantity,
  price,
  label,
  text,
  variant = "primary",
  size = "md",
  fullWidth,
  className,
  style,
  onAdded,
}: AddToCartProps) {
  const [state, setState] = React.useState<"idle" | "loading" | "added" | "error" | "unauth">("idle");

  React.useEffect(() => {
    if (state !== "added" && state !== "error" && state !== "unauth") return;
    const t = setTimeout(() => setState("idle"), 1500);
    return () => clearTimeout(t);
  }, [state]);

  const onClick = async () => {
    if (!entity || itemId == null) return;
    setState("loading");
    try {
      const res = await fetch("/api/cart", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          entity,
          itemId: String(itemId),
          quantity: quantity ?? 1,
          price: price ?? null,
          label: label ?? null,
        }),
      });
      if (res.status === 401) {
        setState("unauth");
        return;
      }
      if (!res.ok) {
        setState("error");
        return;
      }
      setState("added");
      onAdded?.();
      window.dispatchEvent(new CustomEvent("forge-cart-changed"));
    } catch {
      setState("error");
    }
  };

  const labelText =
    state === "loading" ? "Adding…" :
    state === "added" ? "Added" :
    state === "error" ? "Failed" :
    state === "unauth" ? "Sign in to add" :
    text || "Add to cart";

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={state === "loading" || !entity || itemId == null}
      data-add-to-cart=""
      data-state={state}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
      className={[
        "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-opacity disabled:cursor-not-allowed disabled:opacity-60",
        VARIANT_CLASS[variant] ?? VARIANT_CLASS.primary,
        SIZE_CLASS[size] ?? SIZE_CLASS.md,
        fullWidth ? "w-full" : "",
        className ?? "",
      ].filter(Boolean).join(" ")}
    >
      {labelText}
    </button>
  );
}
