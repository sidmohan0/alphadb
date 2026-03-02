import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

interface RootErrorBoundaryState {
  hasError: boolean;
  error?: string;
}

class RootErrorBoundary extends React.Component<
  { children: React.ReactNode },
  RootErrorBoundaryState
> {
  state: RootErrorBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError(error: unknown): RootErrorBoundaryState {
    return {
      hasError: true,
      error: error instanceof Error ? error.message : "Unknown rendering error",
    };
  }

  componentDidCatch(error: unknown): void {
    // Keep the crash visible instead of failing to a blank page.
    // eslint-disable-next-line no-console
    console.error("[discovery-ui] render crash", error);
  }

  render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <main className="app">
          <section className="card error-card">
            <h1>Discovery UI failed to initialize</h1>
            <p>{this.state.error}</p>
            <button type="button" onClick={() => window.location.reload()}>
              Reload page
            </button>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  </React.StrictMode>
);
