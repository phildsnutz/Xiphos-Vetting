import React, { type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { T, FS } from "@/lib/tokens";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error) {
    console.error("ErrorBoundary caught:", error);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = "/";
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          className="h-screen flex items-center justify-center"
          style={{ background: T.bg, color: T.text }}
        >
          <div className="flex flex-col items-center gap-4 max-w-md px-4">
            <div className="rounded-full p-4" style={{ background: T.redBg }}>
              <AlertTriangle size={32} color={T.red} />
            </div>
            <h1 className="font-bold text-center" style={{ fontSize: FS.lg, color: T.text }}>
              Something went wrong
            </h1>
            <p className="text-center" style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.6 }}>
              An unexpected error occurred while rendering the page. Please try again.
            </p>
            {import.meta.env.DEV && this.state.error && (
              <div
                className="w-full rounded p-3 overflow-auto max-h-32"
                style={{ background: T.surface, border: `1px solid ${T.border}` }}
              >
                <code style={{ fontSize: "10px", color: T.muted, fontFamily: "monospace" }}>
                  {this.state.error.message}
                </code>
              </div>
            )}
            <button
              onClick={this.handleReset}
              className="rounded font-medium border cursor-pointer"
              style={{
                padding: "10px 16px",
                fontSize: FS.sm,
                background: T.accent,
                color: "#000",
                border: "none",
              }}
            >
              Try Again
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
