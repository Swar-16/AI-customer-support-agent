// apps/web/src/shared/auth/session-controller.ts

import { SafeApiError } from '../api/safe-error';
import type { TransportResult } from '../api/transport';
import type { createAuthApi } from './auth-api';
import type { AuthenticationResponse, AuthUser, LoginInput, RegisterInput } from './auth-contract';
import { createBrowserSessionCoordinator } from './session-coordinator';
import type { createSessionCoordinator } from './session-coordinator';

type AuthApi = ReturnType<typeof createAuthApi>;

export type SessionPhase =
  'uninitialized' | 'pending' | 'authenticated' | 'anonymous' | 'unavailable';

export interface SessionSnapshot {
  readonly phase: SessionPhase;
  readonly user: Readonly<AuthUser> | null;
  readonly error: SafeApiError | null;
}

export type SessionOutcome =
  | { readonly ok: true }
  | {
      readonly ok: false;
      readonly reason:
        | 'busy'
        | 'reauthentication-required'
        | 'unsupported-account'
        | 'logout-unconfirmed'
        | 'session-changed';
    }
  | {
      readonly ok: false;
      readonly reason: 'request-failed';
      readonly error: SafeApiError;
      readonly retryAfterMs: number | null;
    };

interface SessionControllerOptions {
  readonly createApi: (getAccessToken: () => string | null) => AuthApi;

  /**
   * Synchronously remove private application state.
   * Application wiring will cancel/remove authenticated queries here.
   * This callback must not throw.
   */
  readonly clearPrivateState: () => void;
  readonly createCoordinator?: (
    onRemoteInvalidation: () => void,
  ) => ReturnType<typeof createSessionCoordinator>;
}

type Operation = 'login' | 'register' | 'refresh' | 'logout';

export function createSessionController(options: SessionControllerOptions) {
  let accessToken: string | null = null;
  let accessExpiresAt: number | null = null;
  let refreshExpiresAt: number | null = null;

  let snapshot: SessionSnapshot = Object.freeze({
    phase: 'uninitialized',
    user: null,
    error: null,
  });

  const listeners = new Set<() => void>();
  const api = options.createApi(() => accessToken);

  let active: { readonly operation: Operation; readonly promise: Promise<SessionOutcome> } | null =
    null;

  function publish(
    phase: SessionPhase,
    user: Readonly<AuthUser> | null = null,
    error: SafeApiError | null = null,
  ) {
    snapshot = Object.freeze({ phase, user, error });
    listeners.forEach((listener) => listener());
  }

  function clearCredentials() {
    accessToken = null;
    accessExpiresAt = null;
    refreshExpiresAt = null;
  }

  function removePrivateState() {
    options.clearPrivateState();
  }

  function requestFailure(
    result: Extract<TransportResult<unknown>, { ok: false }>,
    preserveLogoutCredential = false,
  ): SessionOutcome {
    if (!preserveLogoutCredential) clearCredentials();

    removePrivateState();

    publish(
      result.error.status === 401 && !preserveLogoutCredential ? 'anonymous' : 'unavailable',
      null,
      result.error,
    );

    return {
      ok: false,
      reason: 'request-failed',
      error: result.error,
      retryAfterMs: result.retryAfterMs,
    };
  }

  function acceptAuthentication(response: AuthenticationResponse): SessionOutcome {
    const previousUser = snapshot.user;

    accessToken = response.tokens.access_token;
    accessExpiresAt = Date.parse(response.tokens.access_token_expires_at);
    refreshExpiresAt = Date.parse(response.tokens.refresh_token_expires_at);

    if (response.user.status !== 'active' || response.user.role === 'system') {
      removePrivateState();
      publish('unavailable');

      // Retain credentials privately so an explicit logout remains possible.
      return { ok: false, reason: 'unsupported-account' };
    }

    if (
      previousUser !== null &&
      (previousUser.id !== response.user.id ||
        previousUser.role !== response.user.role ||
        previousUser.status !== response.user.status)
    ) {
      removePrivateState();
    }

    publish('authenticated', Object.freeze({ ...response.user }));
    return { ok: true };
  }

  let generation = 0;
  let disposed = false;

  function invalidateLocalSession() {
    generation += 1;
    clearCredentials();
    removePrivateState();
    publish('unavailable');
  }

  const coordinator = (options.createCoordinator ?? createBrowserSessionCoordinator)(() => {
    if (!disposed) {
      invalidateLocalSession();
    }
  });

  function canSend(operation: Operation): boolean {
    if (operation === 'refresh') {
      return snapshot.phase === 'uninitialized' || snapshot.phase === 'authenticated';
    }

    if (operation === 'logout') {
      return accessToken !== null;
    }

    return true;
  }

  function run(
    operation: Operation,
    task: (isCurrent: () => boolean) => Promise<SessionOutcome>,
  ): Promise<SessionOutcome> {
    if (disposed) {
      return Promise.resolve({ ok: false, reason: 'session-changed' });
    }

    if (active !== null) {
      if (operation === 'refresh' && active.operation === 'refresh') {
        return active.promise;
      }

      return Promise.resolve({ ok: false, reason: 'busy' });
    }

    const startedGeneration = generation;
    const isCurrent = () => !disposed && generation === startedGeneration;

    // Assign active before executing work or notifying subscribers.
    const promise = Promise.resolve()
      .then(() =>
        coordinator.runExclusive(
          async (): Promise<SessionOutcome> => {
            if (!isCurrent()) {
              return { ok: false, reason: 'session-changed' };
            }

            // Each task checks its operation-specific preconditions here,
            // after acquiring the shared lock.
            return await task(isCurrent);
          },
          () => isCurrent() && canSend(operation),
        ),
      )
      .catch((cause: unknown): SessionOutcome => {
        if (!isCurrent()) {
          return { ok: false, reason: 'session-changed' };
        }

        clearCredentials();
        removePrivateState();

        const error =
          cause instanceof SafeApiError ? cause : SafeApiError.fromLocal('invalid-response');

        publish('unavailable', null, error);

        return {
          ok: false,
          reason: 'request-failed',
          error,
          retryAfterMs: null,
        };
      })
      .finally(() => {
        active = null;
      });

    active = { operation, promise };
    return promise;
  }

  async function authenticate(
    send: () => Promise<TransportResult<AuthenticationResponse>>,
    isCurrent: () => boolean,
  ): Promise<SessionOutcome> {
    clearCredentials();
    removePrivateState();
    publish('pending');

    // Subscribers may synchronously invalidate or dispose the controller.
    if (!isCurrent()) {
      return { ok: false, reason: 'session-changed' };
    }

    const result = await send();

    if (!isCurrent()) {
      return { ok: false, reason: 'session-changed' };
    }

    return result.ok ? acceptAuthentication(result.data) : requestFailure(result);
  }

  return {
    getSnapshot: (): SessionSnapshot => snapshot,

    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },

    /**
     * Expiry metadata is safe to inspect; token material remains private.
     * The backend is authoritative about actual session validity.
     */
    getExpiry() {
      return Object.freeze({ accessExpiresAt, refreshExpiresAt });
    },

    login(input: LoginInput): Promise<SessionOutcome> {
      // Copy only allowed fields before asynchronous execution.
      const credentials: LoginInput = {
        email: input.email,
        password: input.password,
      };

      return run('login', (isCurrent) => authenticate(() => api.login(credentials), isCurrent));
    },

    register(input: RegisterInput): Promise<SessionOutcome> {
      const registration: RegisterInput = {
        email: input.email,
        password: input.password,
        ...(input.display_name === undefined ? {} : { display_name: input.display_name }),
      };

      return run('register', (isCurrent) =>
        authenticate(() => api.register(registration), isCurrent),
      );
    },

    refresh(): Promise<SessionOutcome> {
      return run('refresh', async (isCurrent) => {
        if (snapshot.phase !== 'uninitialized' && snapshot.phase !== 'authenticated') {
          return { ok: false, reason: 'reauthentication-required' };
        }

        publish('pending', snapshot.user);

        if (!isCurrent()) {
          return { ok: false, reason: 'session-changed' };
        }

        const result = await api.refresh();

        if (!isCurrent()) {
          return { ok: false, reason: 'session-changed' };
        }

        return result.ok ? acceptAuthentication(result.data) : requestFailure(result);
      });
    },

    logout(): Promise<SessionOutcome> {
      return run('logout', async (isCurrent) => {
        removePrivateState();
        publish('pending');

        if (!isCurrent()) {
          return { ok: false, reason: 'session-changed' };
        }

        if (accessToken === null) {
          publish('unavailable');
          return { ok: false, reason: 'logout-unconfirmed' };
        }

        const result = await api.logout();

        if (!isCurrent()) {
          return { ok: false, reason: 'session-changed' };
        }

        if (!result.ok) {
          // A failed request does not prove the cookie was deleted.
          return requestFailure(result, true);
        }

        if (!result.data.logged_out) {
          publish('unavailable');
          return { ok: false, reason: 'logout-unconfirmed' };
        }

        clearCredentials();
        publish('anonymous');
        return { ok: true };
      });
    },
    dispose(): void {
      if (disposed) return;

      disposed = true;
      invalidateLocalSession();
      coordinator.dispose();
      listeners.clear();
    },
  };
}
