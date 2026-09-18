// apps/web/src/shared/auth/session-coordinator.test.ts

import { describe, expect, it, vi } from 'vitest';

import { SafeApiError } from '../api/safe-error';
import { createSessionCoordinator } from './session-coordinator';
import type { SessionCoordinationDependencies } from './session-coordinator';

function deferred<T>() {
  let resolve!: (value: T) => void;

  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });

  return { promise, resolve };
}

/** Deterministic stand-in for the browser's shared exclusive lock. */
function createExclusiveLock() {
  let tail: Promise<void> = Promise.resolve();

  return function exclusive<T>(task: () => Promise<T>): Promise<T> {
    const result = tail.then(task);

    tail = result.then(
      () => undefined,
      () => undefined,
    );

    return result;
  };
}

function setup(exclusive = createExclusiveLock()) {
  let receive: (value: unknown) => void = () => undefined;

  const notify = vi.fn<SessionCoordinationDependencies['notify']>();
  const stopListening = vi.fn();
  const close = vi.fn();
  const onRemoteInvalidation = vi.fn();

  const coordinator = createSessionCoordinator(
    {
      exclusive,
      notify,
      listen(listener) {
        receive = listener;
        return stopListening;
      },
      close,
    },
    onRemoteInvalidation,
  );

  return {
    coordinator,
    notify,
    stopListening,
    close,
    onRemoteInvalidation,
    receive: (value: unknown) => receive(value),
  };
}

describe('session coordinator', () => {
  it('serializes operations from two coordinator instances', async () => {
    const lock = createExclusiveLock();
    const first = setup(lock);
    const second = setup(lock);
    const release = deferred<void>();
    const entered = deferred<void>();
    const order: string[] = [];

    const firstOperation = first.coordinator.runExclusive(async () => {
      order.push('first-start');
      entered.resolve();
      await release.promise;
      order.push('first-end');
    });

    await entered.promise;

    const secondOperation = second.coordinator.runExclusive(async () => {
      order.push('second-start');
    });

    await Promise.resolve();
    expect(order).toEqual(['first-start']);

    release.resolve();
    await Promise.all([firstOperation, secondOperation]);

    expect(order).toEqual(['first-start', 'first-end', 'second-start']);
  });

  it('broadcasts only the fixed invalidation event', async () => {
    const { coordinator, notify } = setup();

    const result = await coordinator.runExclusive(async () => ({
      privateValue: 'test-only-secret',
    }));

    expect(result.privateValue).toBe('test-only-secret');
    expect(notify).toHaveBeenCalledExactlyOnceWith({
      version: 1,
      type: 'session-invalidated',
    });
    expect(JSON.stringify(notify.mock.calls)).not.toContain('test-only-secret');
  });

  it('notifies before executing the mutation', async () => {
    const { coordinator, notify } = setup();

    await coordinator.runExclusive(async () => {
      expect(notify).toHaveBeenCalledTimes(1);
    });
  });

  it('invalidates local state for a recognized remote event', () => {
    const { receive, onRemoteInvalidation } = setup();

    receive({ version: 1, type: 'session-invalidated' });

    expect(onRemoteInvalidation).toHaveBeenCalledTimes(1);
  });

  it.each([
    null,
    [],
    'session-invalidated',
    {},
    { version: 2, type: 'session-invalidated' },
    { version: 1, type: 'authenticated' },
    { version: 1, type: 'session-invalidated', token: 'unexpected' },
  ])('ignores unsupported messages: %j', (message) => {
    const { receive, onRemoteInvalidation } = setup();

    receive(message);

    expect(onRemoteInvalidation).not.toHaveBeenCalled();
  });

  it('sanitizes an unexpected task exception and releases the lock', async () => {
    const lock = createExclusiveLock();
    const first = setup(lock);
    const second = setup(lock);

    await expect(
      first.coordinator.runExclusive(async () => {
        throw new Error('private-provider-details');
      }),
    ).rejects.toThrow('The service returned an unexpected response.');

    await expect(second.coordinator.runExclusive(async () => 'completed')).resolves.toBe(
      'completed',
    );
  });

  it('preserves an existing safe error', async () => {
    const { coordinator } = setup();
    const error = SafeApiError.fromLocal('timeout');

    await expect(
      coordinator.runExclusive(async () => {
        throw error;
      }),
    ).rejects.toBe(error);
  });

  it('does not execute the task if notification fails', async () => {
    const { coordinator, notify } = setup();
    notify.mockImplementation(() => {
      throw new Error('channel unavailable');
    });
    const task = vi.fn(async () => undefined);

    await expect(coordinator.runExclusive(task)).rejects.toBeInstanceOf(SafeApiError);

    expect(task).not.toHaveBeenCalled();
  });

  it('disposes resources once and ignores subsequent events', async () => {
    const { coordinator, stopListening, close, receive, onRemoteInvalidation } = setup();

    coordinator.dispose();
    coordinator.dispose();
    receive({ version: 1, type: 'session-invalidated' });

    expect(stopListening).toHaveBeenCalledTimes(1);
    expect(close).toHaveBeenCalledTimes(1);
    expect(onRemoteInvalidation).not.toHaveBeenCalled();

    const task = vi.fn(async () => undefined);

    await expect(coordinator.runExclusive(task)).rejects.toBeInstanceOf(SafeApiError);
    expect(task).not.toHaveBeenCalled();
  });
});
