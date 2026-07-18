import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@cloudflare/kumo";
import { ArrowsClockwiseIcon, WarningDiamondIcon } from "@phosphor-icons/react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Keeps a render error contained to the content pane so the shell and
 * navigation survive. Navigating to another route remounts this boundary
 * (via a `key` on the route), which clears the error automatically.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("View crashed:", error, info);
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div className="view-error" role="alert">
          <WarningDiamondIcon size={28} weight="fill" />
          <h2>This view hit an error</h2>
          <p>{this.state.error.message || "An unexpected error occurred while rendering."}</p>
          <Button variant="secondary" icon={<ArrowsClockwiseIcon size={16} />} onClick={this.reset}>
            Reload this view
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
