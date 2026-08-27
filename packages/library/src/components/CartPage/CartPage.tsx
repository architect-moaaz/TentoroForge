"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { CartPagePropsType } from "./CartPage.schema";
import { CartPanel } from "../CartPanel/CartPanel";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface CartPageProps extends CartPagePropsType {
  style?: StyleSlotT;
}

export function CartPage({
  title = "Your cart",
  className,
  style,
  ...rest
}: CartPageProps) {
  return (
    <div
      data-cart-page=""
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
      className={["mx-auto w-full max-w-4xl px-4 py-6 sm:px-6", className ?? ""].filter(Boolean).join(" ")}
    >
      <h1 className="mb-6 text-2xl font-semibold text-foreground">{title}</h1>
      <CartPanel title="" {...rest} />
    </div>
  );
}
