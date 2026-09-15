// apps/web/src/app/route-error-boundary.tsx

import { Component } from 'react';
import type { ReactNode } from 'react';

interface Props {
  readonly children: ReactNode;
}

interface State {
  readonly failed: boolean;
}

export class RouteErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="foundation-screen" aria-labelledby="route-error-title">
          <section className="foundation-panel">
            <h1 id="route-error-title">This page could not open.</h1>
            <p role="alert">A required part of the application could not load.</p>
            <button type="button" onClick={() => window.location.reload()}>
              Reload application
            </button>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
