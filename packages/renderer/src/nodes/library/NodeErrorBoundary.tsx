"use client";
// React class component → inherently client-only. Without this directive Next's
// App Router treats the compiled module as a Server Component and the build fails
// with "You're importing a class component… none of its parents are 'use client'".

import { Component, type ReactNode } from "react";

interface Props {
  nodeType: string;
  children: ReactNode;
}
interface State {
  crashed: boolean;
  message: string;
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
          data-invalid-node={this.props.nodeType}
          title={this.state.message}
        >
          ⚠ {this.props.nodeType}: render error
        </span>
      );
    }
    return this.props.children;
  }
}
