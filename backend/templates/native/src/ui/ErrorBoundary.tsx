// The component kit — the net under every screen. A screen that throws while
// it renders would otherwise take the whole app down to a white page (release
// builds do not even show the red box). The root layout wraps the app in this;
// the person sees what happened in a sentence and can try again, and the
// screen's neighbours keep working.

import * as React from "react";
import { ErrorState } from "./States";

interface State { error: Error | null }

export class ErrorBoundary extends React.Component<{ children: React.ReactNode; onReset?: () => void }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error): void {
    console.error("[forge] a screen failed to render:", error);
  }

  render(): React.ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <ErrorState
        title="This screen could not be shown"
        message={this.state.error.message || "An unexpected error stopped it."}
        onRetry={() => { this.setState({ error: null }); this.props.onReset?.(); }}
      />
    );
  }
}
