import { createRef } from 'react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { TransportContext } from '../../shared/api/transport-context';
import type { Conversation } from './chat-contract';
import { chatKeys } from './chat-queries';
import { useConversationClosure } from './use-conversation-closure';

const { session } = vi.hoisted(() => ({
  session: {
    phase: 'authenticated',
    error: null,
    user: {
      id: 'bf187e45-c833-444b-bcc5-39465b2be9fc',
      email: 'customer@example.test',
      display_name: null,
      role: 'customer',
      status: 'active',
      created_at: '2026-09-15T10:00:00Z',
    },
  },
}));

vi.mock('../../shared/auth/session-context', () => ({
  useSession: () => session,
  useSessionController: () => ({
    getSnapshot: () => session,
  }),
}));

const ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';
const CLOSED_AT = '2026-09-15T10:05:00Z';

function conversation(closed = false): Conversation {
  return {
    conversation_id: ID,
    customer_id: session.user.id,
    status: closed ? 'closed' : 'open',
    channel: 'web',
    title: 'Order question',
    created_at: '2026-09-15T10:00:00Z',
    updated_at: closed ? CLOSED_AT : '2026-09-15T10:00:00Z',
    resolved_at: closed ? CLOSED_AT : null,
    closed_at: closed ? CLOSED_AT : null,
  };
}

function closeResponse() {
  return Response.json({
    conversation_id: ID,
    customer_id: session.user.id,
    status: 'closed',
    resolved_at: CLOSED_AT,
    closed_at: CLOSED_AT,
    updated_at: CLOSED_AT,
    changed: true,
  });
}

function setup() {
  const fetchImpl = vi.fn<typeof fetch>();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const key = chatKeys.conversation(session.user.id, ID);
  queryClient.setQueryData(key, conversation());

  const transport = createTransport({
    apiOrigin: 'https://api.example.test',
    getAccessToken: () => 'test-only-token',
    fetchImpl,
  });

  const mutationLockRef = createRef<'send' | 'close' | null>();

  function Wrapper({ children }: { readonly children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <TransportContext.Provider value={transport}>{children}</TransportContext.Provider>
      </QueryClientProvider>
    );
  }

  const view = renderHook(
    () =>
      useConversationClosure({
        conversationId: ID,
        mutationLockRef,
      }),
    { wrapper: Wrapper },
  );

  return {
    ...view,
    fetchImpl,
    mutationLockRef,
    queryClient,
    key,
    dispose() {
      view.unmount();
      queryClient.clear();
    },
  };
}

describe('useConversationClosure', () => {
  it('applies confirmed lifecycle fields while preserving conversation details', async () => {
    const test = setup();
    test.fetchImpl.mockResolvedValue(closeResponse());

    try {
      await act(async () => {
        await test.result.current.close();
      });

      expect(test.result.current.phase).toBe('confirmed');
      expect(test.result.current.blocksSending).toBe(true);

      expect(test.queryClient.getQueryData<Conversation>(test.key)).toMatchObject({
        title: 'Order question',
        channel: 'web',
        status: 'closed',
        closed_at: CLOSED_AT,
      });

      expect(test.fetchImpl).toHaveBeenCalledTimes(1);
    } finally {
      test.dispose();
    }
  });

  it('does not close while a message request holds the shared lock', async () => {
    const test = setup();
    test.mutationLockRef.current = 'send';

    try {
      await act(async () => {
        await test.result.current.close();
      });

      expect(test.fetchImpl).not.toHaveBeenCalled();
      expect(test.mutationLockRef.current).toBe('send');
    } finally {
      test.dispose();
    }
  });

  it('confirms uncertain closure using a GET without repeating the POST', async () => {
    const test = setup();

    test.fetchImpl
      .mockRejectedValueOnce(new Error('Simulated connection loss'))
      .mockResolvedValueOnce(Response.json(conversation(true)));

    try {
      await act(async () => {
        await test.result.current.close();
      });

      expect(test.result.current.phase).toBe('uncertain');
      expect(test.result.current.blocksSending).toBe(true);
      expect(test.result.current.canRetry).toBe(false);

      await act(async () => {
        await test.result.current.checkStatus();
      });

      expect(test.result.current.phase).toBe('confirmed');
      expect(test.queryClient.getQueryData<Conversation>(test.key)?.status).toBe('closed');

      expect(test.fetchImpl.mock.calls.map((call) => call[1]?.method)).toEqual(['POST', 'GET']);
    } finally {
      test.dispose();
    }
  });

  it('keeps sending paused when status reconciliation fails', async () => {
    const test = setup();

    test.fetchImpl.mockRejectedValue(new Error('Simulated connection loss'));

    try {
      await act(async () => {
        await test.result.current.close();
      });

      await act(async () => {
        await test.result.current.checkStatus();
      });

      expect(test.result.current.phase).toBe('uncertain');
      expect(test.result.current.blocksSending).toBe(true);
      expect(test.result.current.canRetry).toBe(false);
      expect(test.result.current.notice).toContain('Closure remains unconfirmed');
    } finally {
      test.dispose();
    }
  });

  it('allows one explicit retry after an open-state read, despite rapid clicks', async () => {
    const test = setup();

    test.fetchImpl
      .mockRejectedValueOnce(new Error('Simulated connection loss'))
      .mockResolvedValueOnce(Response.json(conversation()))
      .mockResolvedValueOnce(closeResponse());

    try {
      await act(async () => {
        await test.result.current.close();
      });

      await act(async () => {
        await test.result.current.checkStatus();
      });

      expect(test.result.current.canRetry).toBe(true);
      expect(test.result.current.blocksSending).toBe(true);

      // Both calls deliberately use the same render's callback.
      const closeAgain = test.result.current.close;

      await act(async () => {
        await Promise.all([closeAgain(), closeAgain()]);
      });

      expect(test.result.current.phase).toBe('confirmed');
      expect(test.fetchImpl.mock.calls.map((call) => call[1]?.method)).toEqual([
        'POST',
        'GET',
        'POST',
      ]);
    } finally {
      test.dispose();
    }
  });

  it('releases the mutation lock after a definitive HTTP rejection', async () => {
    const test = setup();

    test.fetchImpl.mockResolvedValue(
      Response.json(
        {
          error: {
            code: 'TEST_FORBIDDEN',
            message: 'Test rejection.',
          },
        },
        { status: 403 },
      ),
    );

    try {
      await act(async () => {
        await test.result.current.close();
      });

      expect(test.result.current.phase).toBe('idle');
      expect(test.result.current.blocksSending).toBe(false);
      expect(test.mutationLockRef.current).toBeNull();
      expect(test.result.current.notice).not.toBeNull();
      expect(test.fetchImpl).toHaveBeenCalledTimes(1);
    } finally {
      test.dispose();
    }
  });
});
