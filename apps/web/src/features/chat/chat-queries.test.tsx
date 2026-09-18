// apps/web/src/features/chat/chat-queries.test.tsx

import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { ApplicationProviders } from '../../app/providers';
import { createApplicationRuntime } from '../../app/runtime';
import { createSessionCoordinator } from '../../shared/auth/session-coordinator';
import { useConversations } from './chat-queries';

const CUSTOMER_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';

async function setup() {
  const fetchImpl = vi.fn<typeof fetch>();
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
          close: () => undefined,
        },
        onRemoteInvalidation,
      );
    },
  });

  fetchImpl.mockResolvedValueOnce(
    Response.json({
      user: {
        id: CUSTOMER_ID,
        email: 'customer@example.test',
        display_name: null,
        role: 'customer',
        status: 'active',
        created_at: '2026-09-15T10:00:00Z',
      },
      tokens: {
        access_token: 'test-only-token',
        token_type: 'Bearer',
        access_token_expires_at: '2026-09-15T10:15:00Z',
        refresh_token_expires_at: '2026-10-15T10:00:00Z',
      },
    }),
  );

  await runtime.session.login({
    email: 'customer@example.test',
    password: 'test-only-password',
  });

  fetchImpl.mockClear();

  function Wrapper({ children }: { readonly children: ReactNode }) {
    return <ApplicationProviders runtime={runtime}>{children}</ApplicationProviders>;
  }

  return {
    runtime,
    fetchImpl,
    Wrapper,
    invalidate() {
      receive({ version: 1, type: 'session-invalidated' });
    },
  };
}

describe('Chat query integration', () => {
  it('loads a customer-scoped page through the authenticated runtime', async () => {
    const { runtime, fetchImpl, Wrapper } = await setup();

    fetchImpl.mockResolvedValueOnce(
      Response.json({
        items: [],
        total: 0,
        count: 0,
        limit: 25,
        offset: 0,
        has_more: false,
        next_offset: null,
      }),
    );

    const view = renderHook(() => useConversations(0, 25), {
      wrapper: Wrapper,
    });

    await waitFor(() => {
      expect(view.result.current.isSuccess).toBe(true);
    });

    const url = new URL(String(fetchImpl.mock.calls[0]?.[0]));
    expect(url.pathname).toBe('/v1/conversations');
    expect(url.searchParams.get('limit')).toBe('25');
    expect(url.searchParams.get('offset')).toBe('0');

    const query = runtime.queryClient.getQueryCache().getAll()[0];
    expect(query?.queryKey).toEqual([
      'chat',
      CUSTOMER_ID,
      'conversations',
      { limit: 25, offset: 0 },
    ]);

    view.unmount();
    runtime.dispose();
  });

  it('rejects a late response after remote session invalidation', async () => {
    const { runtime, fetchImpl, invalidate } = await setup();
    let finish!: (response: Response) => void;

    fetchImpl.mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
    );

    const pending = runtime.request({
      path: '/v1/conversations',
      method: 'GET',
      authentication: 'bearer',
      decode: () => ({ privateRecord: 'test-only-private-data' }),
    });

    invalidate();

    finish(Response.json({}));
    const result = await pending;

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected stale response rejection');

    expect(result.error.kind).toBe('aborted');
    expect(JSON.stringify(result)).not.toContain('test-only-private-data');

    runtime.dispose();
  });

  it('blocks feature requests after session invalidation', async () => {
    const { runtime, fetchImpl, invalidate } = await setup();

    act(() => {
      invalidate();
    });

    const result = await runtime.request({
      path: '/v1/conversations',
      method: 'GET',
      authentication: 'bearer',
      decode: () => null,
    });

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();

    runtime.dispose();
  });

  it('does not expose cookie authentication through the feature transport', async () => {
    const { runtime, fetchImpl } = await setup();

    const result = await runtime.request({
      path: '/v1/auth/refresh',
      method: 'POST',
      authentication: 'cookie',
      decode: () => null,
    });

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();

    runtime.dispose();
  });
});
