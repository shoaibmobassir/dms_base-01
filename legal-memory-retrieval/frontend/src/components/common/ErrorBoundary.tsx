import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "./primitives";

type Props = {
  children: ReactNode;
  /** What failed, in the person's words ("This page", "This tab"). */
  what?: string;
  /** Extra actions next to "Try again" (e.g. close the tab). */
  actions?: ReactNode;
  /** Changing this value clears the error (e.g. the route path). */
  resetKey?: unknown;
  className?: string;
};

type State = { error: Error | null; resetKey: unknown };

/** A part of the screen that failed to render: say so and offer a way out, instead of blanking the whole app. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey !== state.resetKey ? { error: null, resetKey: props.resetKey } : null;
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Render failed", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    // A code chunk that cannot be fetched usually means the app was updated since this page loaded.
    const stale = /dynamically imported module|Loading chunk|Importing a module script failed/i.test(error.message);
    return (
      <div className={this.props.className ?? "flex h-full items-center justify-center p-6"} role="alert" data-testid="error-boundary">
        <div className="max-w-md space-y-3 text-center">
          <Icon name="error" className="text-destructive" style={{ fontSize: 28 }} />
          <h2 className="font-display text-xl text-ink">{this.props.what ?? "This part of the page"} could not open</h2>
          <p className="text-sm text-muted-foreground">
            {stale
              ? "Precentis was updated since this page loaded. Reload to get the new version; nothing you saved is lost."
              : "Something went wrong while showing it. Nothing you saved is lost."}
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            {stale ? (
              <Button onClick={() => window.location.reload()}>Reload</Button>
            ) : (
              <Button variant="outline" onClick={() => this.setState({ error: null })}>Try again</Button>
            )}
            {this.props.actions}
          </div>
        </div>
      </div>
    );
  }
}
