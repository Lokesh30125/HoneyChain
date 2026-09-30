import { Component } from 'react';
import { RefreshCw, ServerCrash } from 'lucide-react';

/**
 * Top-level error boundary.
 *
 * Catches render-time crashes so the user sees an explanation instead of a blank
 * page. Errors are logged to the console with the component stack; in a later
 * phase this is where client-side error reporting would be wired in.
 */
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Never includes user credentials: React only reports the component stack.
    console.error('HoneyChain UI error:', error, info?.componentStack);
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    const { error } = this.state;

    if (!error) return this.props.children;

    return (
      <div className="flex min-h-screen items-center justify-center bg-sand-50 px-4">
        <div className="max-w-lg text-center">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-status-danger-bg text-status-danger">
            <ServerCrash size={26} aria-hidden="true" />
          </span>
          <h1 className="mt-5 text-xl font-semibold text-ink">Something went wrong in the interface</h1>
          <p className="mt-2 text-sm text-ink-soft">
            The page could not be displayed. Reloading usually resolves this. If it keeps happening,
            report the message below to the platform team.
          </p>
          <pre className="mt-4 overflow-x-auto rounded-lg border border-sand-300 bg-white p-3 text-left font-mono text-xs text-ink-muted">
            {String(error?.message || error)}
          </pre>
          <button
            type="button"
            onClick={this.handleReload}
            className="mt-5 inline-flex h-11 items-center gap-2 rounded-lg bg-forest-700 px-5 text-sm font-medium text-white transition-colors hover:bg-forest-800"
          >
            <RefreshCw size={16} aria-hidden="true" />
            Reload the application
          </button>
        </div>
      </div>
    );
  }
}

export default ErrorBoundary;
