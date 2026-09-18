// apps/web/src/shared/auth/session-coordinator.ts

import { SafeApiError } from '../api/safe-error';

const LOCK_NAME = 'support-ai:auth-mutation:v1';
const CHANNEL_NAME = 'support-ai:session-events:v1';

interface SessionEvent {
  readonly version: 1;
  readonly type: 'session-invalidated';
}

const INVALIDATION_EVENT: SessionEvent = Object.freeze({
  version: 1,
  type: 'session-invalidated',
});

export interface SessionCoordinationDependencies {
  readonly exclusive: <T>(task: () => Promise<T>) => Promise<T>;
  readonly notify: (event: SessionEvent) => void;
  readonly listen: (listener: (value: unknown) => void) => () => void;
  readonly close: () => void;
}

function isInvalidationEvent(value: unknown): boolean {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return false;
  }

  const event = value as Record<string, unknown>;

  return (
    Object.keys(event).length === 2 && event.version === 1 && event.type === 'session-invalidated'
  );
}

/**
 * Serializes participating tabs' authentication mutations.
 *
 * Notifications only invalidate local state. They must never authenticate
 * a user, carry credentials, or trigger an automatic refresh.
 */
export function createSessionCoordinator(
  dependencies: SessionCoordinationDependencies,
  onRemoteInvalidation: () => void,
) {
  let disposed = false;

  const stopListening = dependencies.listen((value) => {
    if (!disposed && isInvalidationEvent(value)) {
      onRemoteInvalidation();
    }
  });

  return {
    async runExclusive<T>(
      task: () => Promise<T>,
      shouldNotify: () => boolean = () => true,
    ): Promise<T> {
      if (disposed) {
        throw SafeApiError.fromLocal('invalid-response');
      }

      try {
        return await dependencies.exclusive(async () => {
          // The coordinator may have been disposed while waiting.
          if (disposed) {
            throw SafeApiError.fromLocal('invalid-response');
          }

          // Tell other tabs to discard stale state before changing the session.
          // This message contains no task input, result, user, or token.
          if (shouldNotify()) {
            dependencies.notify(INVALIDATION_EVENT);
          }

          // Hold the lock through response handling and local state updates.
          return await task();
        });
      } catch (error: unknown) {
        if (error instanceof SafeApiError) {
          throw error;
        }

        // Do not expose browser exceptions or arbitrary task errors.
        throw SafeApiError.fromLocal('invalid-response');
      }
    },

    dispose() {
      if (disposed) return;

      disposed = true;
      stopListening();
      dependencies.close();
    },
  };
}

/**
 * Instantiate once during application bootstrap, not during React rendering.
 * There is deliberately no uncoordinated fallback.
 */
export function createBrowserSessionCoordinator(onRemoteInvalidation: () => void) {
  if (
    typeof navigator === 'undefined' ||
    !navigator.locks ||
    typeof BroadcastChannel === 'undefined'
  ) {
    throw new Error('This browser cannot safely coordinate authentication across tabs.');
  }

  const channel = new BroadcastChannel(CHANNEL_NAME);

  return createSessionCoordinator(
    {
      exclusive: async <T>(task: () => Promise<T>): Promise<T> => {
        return await navigator.locks.request(LOCK_NAME, { mode: 'exclusive' }, task);
      },

      notify: (event) => {
        channel.postMessage(event);
      },

      listen: (listener) => {
        const handler = (event: MessageEvent<unknown>) => listener(event.data);

        channel.addEventListener('message', handler);

        return () => {
          channel.removeEventListener('message', handler);
        };
      },

      close: () => {
        channel.close();
      },
    },
    onRemoteInvalidation,
  );
}
