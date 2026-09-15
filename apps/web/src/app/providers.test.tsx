// apps/web/src/app/providers.test.tsx

import { StrictMode } from 'react';
import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useSession } from '../shared/auth/session-context';
import { createSessionCoordinator } from '../shared/auth/session-coordinator';
import { ApplicationProviders } from './providers';
import { createApplicationRuntime } from './runtime';

function authenticationFixture() {
  return {
    user: {
      id: 'd44e99cb-8e10-4af8-9bb7-c4d293042943',
      email: 'customer@example.test',
      display_name: 'Customer',
      role: 'customer',
      status: 'active',
      created_at: '2026-09-15T10:00:00Z',
    },
    tokens: {
      access_token: 'test-only-private-token',
      token_type: 'Bearer',
      access_token_expires_at: '2026-09-15T10:15:00Z',
      refresh_token_expires_at: '2026-10-15T10:00:00Z',
    },
  };
}

function setup() {
  const fetchImpl = vi.fn<typeof fetch>();
  const close = vi.fn();
  let receive: (value: unknown) => void = () => undefined;

  const runtime = createApplicationRuntime({
    apiOrigin: 'https://api.example.test',
    fetchImpl,

    createCoordinator(onRemoteInvalidation) {
      return createSessionCoordinator(
        {
          exclusive: async <T,>(task: () => Promise<T>): Promise<T> => await task(),

          notify: () => undefined,

          listen(listener) {
            receive = listener;
            return () => {
              receive = () => undefined;
            };
          },

          close,
        },
        onRemoteInvalidation,
      );
    },
  });

  return {
    runtime,
    fetchImpl,
    close,
    invalidateRemotely: () => receive({ version: 1, type: 'session-invalidated' }),
  };
}

function SessionProbe() {
  const session = useSession();

  return <p role="status">{session.phase}</p>;
}

describe('application providers and runtime', () => {
  it('does not start authentication merely by mounting in Strict Mode', () => {
    const { runtime, fetchImpl } = setup();

    const view = render(
      <StrictMode>
        <ApplicationProviders runtime={runtime}>
          <SessionProbe />
        </ApplicationProviders>
      </StrictMode>,
    );

    expect(screen.getByRole('status')).toHaveTextContent('uninitialized');
    expect(fetchImpl).not.toHaveBeenCalled();

    view.unmount();
    runtime.dispose();
  });

  it('shares startup and updates React without caching access credentials', async () => {
    const { runtime, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(authenticationFixture()));

    const view = render(
      <StrictMode>
        <ApplicationProviders runtime={runtime}>
          <SessionProbe />
        </ApplicationProviders>
      </StrictMode>,
    );

    await act(async () => {
      const first = runtime.start();
      const second = runtime.start();

      expect(first).toBe(second);
      await first;
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('status')).toHaveTextContent('authenticated');
    expect(runtime.queryClient.getQueryCache().getAll()).toHaveLength(0);
    expect(runtime.queryClient.getMutationCache().getAll()).toHaveLength(0);
    expect(view.container.textContent).not.toContain('test-only-private-token');

    act(() => {
      runtime.dispose();
    });
    view.unmount();
  });

  it('clears caches and updates React after remote invalidation', async () => {
    const { runtime, fetchImpl, invalidateRemotely } = setup();
    fetchImpl.mockResolvedValue(Response.json(authenticationFixture()));

    await runtime.start();

    const view = render(
      <ApplicationProviders runtime={runtime}>
        <SessionProbe />
      </ApplicationProviders>,
    );

    runtime.queryClient.setQueryData(['private-fixture'], {
      value: 'private-test-data',
    });

    runtime.queryClient.getMutationCache().build(runtime.queryClient, {
      mutationKey: ['private-mutation-fixture'],
      mutationFn: async () => undefined,
    });

    act(() => {
      invalidateRemotely();
    });

    expect(screen.getByRole('status')).toHaveTextContent('unavailable');
    expect(runtime.queryClient.getQueryCache().getAll()).toHaveLength(0);
    expect(runtime.queryClient.getMutationCache().getAll()).toHaveLength(0);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    view.unmount();
    runtime.dispose();
  });

  it('aborts an in-flight query when private state is cleared', async () => {
    const { runtime, invalidateRemotely } = setup();
    let wasAborted = false;

    const pending = runtime.queryClient
      .fetchQuery({
        queryKey: ['in-flight-private-fixture'],
        queryFn: ({ signal }) =>
          new Promise<string>((_resolve, reject) => {
            signal.addEventListener(
              'abort',
              () => {
                wasAborted = true;
                reject(new Error('Test request aborted'));
              },
              { once: true },
            );
          }),
      })
      .catch(() => undefined);

    invalidateRemotely();
    await pending;

    expect(wasAborted).toBe(true);
    expect(runtime.queryClient.getQueryCache().getAll()).toHaveLength(0);

    runtime.dispose();
  });

  it('does not repeat an unsuccessful startup attempt', async () => {
    const { runtime, fetchImpl } = setup();
    fetchImpl.mockRejectedValue(new Error('Test network failure'));

    const first = runtime.start();
    await first;

    expect(runtime.start()).toBe(first);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(runtime.session.getSnapshot().phase).toBe('unavailable');

    runtime.dispose();
  });

  it('disposes once and prevents subsequent startup', async () => {
    const { runtime, fetchImpl, close } = setup();

    runtime.dispose();
    runtime.dispose();

    await expect(runtime.start()).resolves.toEqual({
      ok: false,
      reason: 'session-changed',
    });

    expect(close).toHaveBeenCalledTimes(1);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
