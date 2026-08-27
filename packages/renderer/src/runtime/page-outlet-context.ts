"use client";
import { createContext, type ReactNode } from "react";

/**
 * PageOutletContext holds the ReactNode that should be rendered in place of
 * every <PageOutlet /> node in a shell schema. The scaffold wraps the shell
 * schema renderer in a Provider whose value is the page's own rendered content,
 * so the shell's navigation bar and the page body compose correctly without
 * duplicating the nav in every per-page schema.
 *
 * Default is null — rendering a PageOutlet outside of a Provider is a no-op
 * (returns null), which is the right fallback for direct page renders.
 */
export const PageOutletContext = createContext<ReactNode>(null);
