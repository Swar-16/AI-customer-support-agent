// apps/web/src/app/runtime.ts

import { QueryClient } from '@tanstack/react-query';

import { createTransport } from '../shared/api/transport';
import { createAuthApi } from '../shared/auth/auth-api';
import { createSessionController } from '../shared/auth/session-controller';
import type { SessionOutcome } from '../shared/auth/session-controller';
import type { createSessionCoordinator } from '../shared/auth/session-coordinator';
import { SafeApiError } from '../shared/api/safe-error';
import type { TransportRequest, TransportResult } from '../shared/api/transport';

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

  let sessionGeneration = 0;
  let readAccessToken: () => string | null = () => null;

  const transport = createTransport({
    apiOrigin: options.apiOrigin,
    getAccessToken: () => readAccessToken(),
    ...(options.fetchImpl === undefined ? {} : { fetchImpl: options.fetchImpl }),
  });

  const session = createSessionController({
    createApi(getAccessToken) {
      readAccessToken = getAccessToken;
      return createAuthApi(transport);
    },

    clearPrivateState() {
      sessionGeneration += 1;
      queryClient.clear();
    },

    ...(options.createCoordinator === undefined
      ? {}
      : { createCoordinator: options.createCoordinator }),
  });

  let startup: Promise<SessionOutcome> | null = null;
  let disposed = false;
  async function request<T>(input: TransportRequest<T>): Promise<TransportResult<T>> {
    const snapshot = session.getSnapshot();

    if (disposed || snapshot.phase !== 'authenticated') {
      return {
        ok: false,
        error: SafeApiError.fromHttp(401, null),
        retryAfterMs: null,
      };
    }

    // Feature requests use bearer authentication. Cookie-based auth
    // operations remain private to the session controller.
    if (input.authentication !== 'bearer') {
      return {
        ok: false,
        error: SafeApiError.fromLocal('invalid-response'),
        retryAfterMs: null,
      };
    }

    const generation = sessionGeneration;
    const result = await transport(input);
    const current = session.getSnapshot();

    if (
      disposed ||
      generation !== sessionGeneration ||
      current.phase !== 'authenticated' ||
      current.user?.id !== snapshot.user?.id ||
      current.user?.role !== snapshot.user?.role
    ) {
      return {
        ok: false,
        error: SafeApiError.fromLocal('aborted'),
        retryAfterMs: null,
      };
    }

    return result;
  }

  return {
    queryClient,
    session,
    request,

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
