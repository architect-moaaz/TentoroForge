"use client";
// React class component → inherently client-only. Without this directive Next's
// App Router treats the compiled module as a Server Component and the build fails
// with "You're importing a class component… none of its parents are 'use client'".

import { Component, Suspense, type ReactNode } from "react";

interface Props {
  nodeType: string;
  /** Schema id of the node being rendered. See WHY THE ID MATTERS below. */
  nodeId?: string;
  /**
   * The props the component was handed. Read ONLY to name the prop that most
   * likely caused the throw — never rendered wholesale.
   */
  nodeProps?: Record<string, unknown>;
  children: ReactNode;
}
interface State {
  crashed: boolean;
  message: string;
}

/**
 * Best-effort guess at WHICH prop broke the node, so the placeholder can say
 * "AppShell: render error — sidebar" instead of only that something failed.
 *
 * The motivating case is the one in docs/editor-audit/containment.md:
 * `<AppShell sidebar={{action:"navigate"}}/>` throws "Objects are not valid as
 * a React child (found: object with keys {action})". React names the KEYS of
 * the offending object but not the prop that held it, so we match those keys
 * back against the node's props. Falls back to a prop name mentioned verbatim
 * in the message.
 *
 * Everything here runs inside an error path, so it must not throw: any
 * surprise (a getter that explodes, a Proxy, a frozen exotic object) returns
 * undefined and the placeholder simply omits the prop name.
 */
function guessFailingProp(
  message: string,
  props: Record<string, unknown> | undefined,
): string | undefined {
  try {
    if (!props || typeof props !== "object") return undefined;
    const names = Object.keys(props).filter((k) => k !== "style" && k !== "children");

    const keyList = /keys \{([^}]*)\}/.exec(message)?.[1];
    if (keyList) {
      const wanted = keyList.split(",").map((s) => s.trim()).filter(Boolean);
      if (wanted.length > 0) {
        for (const name of names) {
          const v = props[name];
          if (!v || typeof v !== "object" || Array.isArray(v)) continue;
          const own = Object.keys(v as Record<string, unknown>);
          if (wanted.every((k) => own.includes(k))) return name;
        }
      }
    }

    // Longest first: "options" should win over "option" when both are present.
    for (const name of [...names].sort((a, b) => b.length - a.length)) {
      if (name.length > 2 && message.includes(name)) return name;
    }
    return undefined;
  } catch {
    return undefined;
  }
}

/** The single labelled placeholder every containment path renders. */
function InvalidNodePlaceholder({
  nodeType,
  nodeId,
  message,
  failingProp,
}: {
  nodeType: string;
  nodeId?: string;
  message?: string;
  failingProp?: string;
}) {
  // Keep the placeholder to one line: the full text lives in `title`.
  const detail = failingProp
    ? ` — ${failingProp}`
    : message
      ? ` — ${message.length > 60 ? `${message.slice(0, 60)}…` : message}`
      : "";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 8px",
        margin: "2px",
        border: "1px dashed hsl(var(--destructive, 0 70% 50%))",
        borderRadius: 4,
        background: "hsl(var(--destructive, 0 70% 50%) / 0.08)",
        color: "hsl(var(--destructive, 0 70% 50%))",
        fontSize: 12,
        fontFamily: "ui-sans-serif, system-ui, sans-serif",
      }}
      // WHY THE ID MATTERS: the editor resolves a canvas click to a node by
      // walking up to the nearest [data-node-id]. Without it here, clicking the
      // error box selected the node's PARENT — so the one node the author had
      // just broken was the one node they could not open in the Properties
      // panel to fix, and the only way back was the layer tree.
      data-node-id={nodeId}
      data-invalid-node={nodeType}
      data-failing-prop={failingProp}
      title={message}
    >
      ⚠ {nodeType}: render error{detail}
    </span>
  );
}

/**
 * Per-node error boundary for library components. A library component that
 * throws during render (e.g. it calls `.map` on a prop the schema couldn't
 * fully satisfy, or hits an unexpected runtime value) would otherwise unwind
 * React and blank the ENTIRE canvas. This isolates the failure to a single
 * inline placeholder so the rest of the page keeps rendering and the editor
 * stays usable.
 *
 * It resets itself whenever `children` change by reference — every editor
 * edit produces a fresh node tree, so a node fixed by the user will re-attempt
 * its render instead of staying stuck on the placeholder.
 *
 * WHY THE INNER <Suspense>: a class boundary alone contains nothing during
 * server rendering. react-dom/server (Fizz) never calls
 * getDerivedStateFromError / componentDidCatch — the ONLY unit of error
 * containment it understands is a Suspense boundary. Proven against the React
 * 19.2.4 in this repo: renderToStaticMarkup of
 * <EB><Bad sidebar={{action:"navigate"}}/></EB> threw
 * "Objects are not valid as a React child" straight out of the renderer even
 * with the class boundary in place, so a single bad prop on ONE node took the
 * whole SSR document with it and Next replaced <body> with its error template
 * — the AppShell blank-page finding in docs/editor-audit/containment.md.
 * Wrapping the children in a Suspense boundary confines that same throw to one
 * node: every sibling still renders, and the client then re-renders the
 * errored boundary, where the class boundary catches and paints the labelled
 * placeholder.
 */
export class NodeErrorBoundary extends Component<Props, State> {
  state: State = { crashed: false, message: "" };

  static getDerivedStateFromError(err: unknown): State {
    return {
      crashed: true,
      message: err instanceof Error ? err.message : String(err),
    };
  }

  componentDidUpdate(prev: Props) {
    if (this.state.crashed && prev.children !== this.props.children) {
      this.setState({ crashed: false, message: "" });
    }
  }

  render() {
    if (this.state.crashed) {
      return (
        <InvalidNodePlaceholder
          nodeType={this.props.nodeType}
          nodeId={this.props.nodeId}
          message={this.state.message}
          failingProp={guessFailingProp(this.state.message, this.props.nodeProps)}
        />
      );
    }
    // The fallback is deliberately INVISIBLE, not the error placeholder. Fizz
    // uses this same fallback for two different situations — a boundary that
    // errored, and a boundary that is merely still streaming — and it cannot
    // tell the renderer which. AppShell is a live example: it suspends under
    // Next's streaming SSR (its emitted HTML carries `<!--$?-->` + a
    // `<template id="B:n">` swap marker), so an error-styled fallback painted a
    // red "render error" box on every healthy AppShell for the first frame.
    // Invisible means a suspending node just appears when it streams in, while
    // a node that genuinely threw leaves a hole in the SSR HTML — and React
    // then re-renders that boundary on the client, where the class boundary
    // above catches the same throw and paints the labelled placeholder.
    return (
      <Suspense
        fallback={
          <span
            data-node-pending={this.props.nodeType}
            style={{ display: "contents" }}
          />
        }
      >
        {this.props.children}
      </Suspense>
    );
  }
}
