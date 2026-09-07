"use client";
import * as React from "react";
import type { NavFlowT } from "@tentoroforge/schema";

export const NavFlowContext = React.createContext<NavFlowT | null>(null);

export function useNavFlow(): NavFlowT | null {
  return React.useContext(NavFlowContext);
}
