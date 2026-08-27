"use client";
import { useContext } from "react";
import { WorkflowDispatcherContext, tokenToCssVar, useNavigator } from "@tentoroforge/renderer";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

type Props = {
  label: string;
  navigate: string;
  workflow?: string;
  args?: Record<string, unknown>;
  style?: StyleSlotT;
  /** Schema-authored utility classes. When present the class is authoritative
   * for the link's look: the default underline/color inline styles are dropped
   * so `bg-*`/`text-*`/`no-underline` classes can style it as a button. */
  className?: string;
  /** Test injection only — allows bypassing context in unit tests. */
  __dispatch?: (workflow: string, args?: Record<string, unknown>) => void;
};

export function Link({ label, navigate, workflow, args, style, className, __dispatch }: Props) {
  const ctxDispatch = useContext(WorkflowDispatcherContext);
  const nav = useNavigator();

  const onClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (workflow) {
      const dispatch = __dispatch ?? ctxDispatch;
      if (dispatch) dispatch(workflow, args);
    }
    // Route internal links through the Navigator (soft nav + routed modals).
    // Keep the <a href> for accessibility / new-tab / crawlers, but hijack the
    // plain left-click. Modifier clicks and external URLs fall through to the
    // browser's default so open-in-new-tab still works.
    if (
      navigate &&
      navigate.startsWith("/") &&
      !e.defaultPrevented &&
      e.button === 0 &&
      !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey
    ) {
      e.preventDefault();
      nav.push(navigate);
    }
  };

  const defaultLook = className
    ? {}
    : {
        color: `var(${tokenToCssVar("primary.500")})`,
        textDecoration: "underline" as const,
        fontSize: `var(${tokenToCssVar("typography.base")})`,
      };
  return (
    <a
      href={navigate}
      onClick={onClick}
      className={className}
      style={{
        ...defaultLook,
        cursor: "pointer",
        ...resolveStyle(style),
      }}
      {...useMotion(style?.motion)}
    >
      {label}
    </a>
  );
}
