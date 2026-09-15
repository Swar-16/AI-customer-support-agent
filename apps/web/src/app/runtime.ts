// apps/web/src/app/runtime.ts

import { QueryClient } from '@tanstack/react-query';

import { createTransport } from '../shared/api/transport';
import { createAuthApi } from '../shared/auth/auth-api';
import { createSessionController } from '../shared/auth/session-controller';
import type { SessionOutcome } from '../shared/auth/session-controller';
import type { createSessionCoordinator } from '../shared/auth/session-coordinator';

interface RuntimeOptions {
  /** Supply apiOrigin from readPublicConfig. */
  readonly apiOrigin: string;
  readonly fetchImpl?: typeof fetch;
  readonly createCoordinator?: (
    onRemoteInvalidation: () => void,
  ) => ReturnType<typeof createSessionCoordinator>;
}

export function createApplicationRuntime(options: RuntimeOptions) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
      mutations: {
        retry: false,
      },
    },
  });

  const session = createSessionController({
    createApi(getAccessToken) {
      return createAuthApi(
        createTransport({
          apiOrigin: options.apiOrigin,
          getAccessToken,
          ...(options.fetchImpl === undefined ? {} : { fetchImpl: options.fetchImpl }),
        }),
      );
    },

    clearPrivateState() {
      // Clears queries and mutation records. Destroyed queries cancel their
      // retryers and abort query signals consumed by their request functions.
      queryClient.clear();
    },

    ...(options.createCoordinator === undefined
      ? {}
      : { createCoordinator: options.createCoordinator }),
  });

  let startup: Promise<SessionOutcome> | null = null;
  let disposed = false;

  return {
    queryClient,
    session,

    /**
     * Call explicitly during application bootstrap, outside React rendering.
     * Repeated calls share the original startup attempt, including failures.
     */
    start(): Promise<SessionOutcome> {
      if (disposed) {
        return Promise.resolve({ ok: false, reason: 'session-changed' });
      }

      if (startup === null) {
        startup =
          session.getSnapshot().phase === 'uninitialized'
            ? session.refresh()
            : Promise.resolve({
                ok: false,
                reason: 'reauthentication-required',
              });
      }

      return startup;
    },

    dispose(): void {
      if (disposed) return;

      disposed = true;
      session.dispose();
      queryClient.clear();
    },
  };
}

export type ApplicationRuntime = ReturnType<typeof createApplicationRuntime>;
