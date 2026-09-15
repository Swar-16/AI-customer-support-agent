// apps/web/src/main.tsx

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import '@fontsource-variable/inter';
import '@fontsource-variable/newsreader';

import { ApplicationRouter } from './app/application-router';
import { ApplicationProviders } from './app/providers';
import { createApplicationRuntime } from './app/runtime';
import type { ApplicationRuntime } from './app/runtime';
import { StartupFailure } from './app/startup-failure';
import { PublicConfigurationError, readPublicConfig } from './shared/config/public-config';

import './shared/styles/globals.css';

const container = document.getElementById('root');

if (container === null) {
  throw new Error('Application root element is missing.');
}

const root = createRoot(container);

let runtime: ApplicationRuntime | null = null;
let disposed = false;

function showStartupFailure(reason: 'configuration' | 'startup') {
  if (disposed) return;

  root.render(
    <StrictMode>
      <StartupFailure reason={reason} />
    </StrictMode>,
  );
}

try {
  const config = readPublicConfig(import.meta.env.VITE_API_BASE_URL, window.location.origin);

  runtime = createApplicationRuntime({
    apiOrigin: config.apiOrigin,
  });
} catch (error: unknown) {
  // Never render configuration values, exception messages, or stack traces.
  showStartupFailure(error instanceof PublicConfigurationError ? 'configuration' : 'startup');
}

if (runtime !== null) {
  const applicationRuntime = runtime;

  root.render(
    <StrictMode>
      <ApplicationProviders runtime={applicationRuntime}>
        <ApplicationRouter />
      </ApplicationProviders>
    </StrictMode>,
  );

  // Expected HTTP/auth failures resolve to SessionOutcome and remain in
  // session state. Only an unexpected rejected promise reaches this handler.
  void applicationRuntime.start().catch(() => {
    if (disposed) return;

    applicationRuntime.dispose();
    showStartupFailure('startup');
  });
}

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    disposed = true;
    root.unmount();
    runtime?.dispose();
    runtime = null;
  });
}
