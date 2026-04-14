"use client";

import { Component, type ReactNode } from "react";

interface Props {
  fallback?: ReactNode;
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error) {
    console.error("[ErrorBoundary] Component crashed:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-400">
            Something went wrong rendering this section.
            {this.state.error && (
              <pre className="mt-2 text-xs text-red-300/60 font-mono">
                {this.state.error.message}
              </pre>
            )}
          </div>
        )
      );
    }
    return this.props.children;
  }
}
