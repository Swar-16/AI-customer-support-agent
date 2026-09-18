// apps/web/src/features/chat/use-chat-submission.optimistic.test.tsx
import type { ReactNode } from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useChatSubmission } from './use-chat-submission';

const mocks = vi.hoisted(() => {
  const session = {
    phase: 'authenticated',
    user: { id: 'customer-1', role: 'customer', status: 'active' },
  };
  return {
    session,
    getSnapshot: vi.fn(() => session),
    listeners: new Set<() => void>(),
    send: vi.fn(),
    get: vi.fn(),
    history: vi.fn(),
  };
});
vi.mock('../../shared/auth/session-context', () => ({
  useSession: () => mocks.session,
  useSessionController: () => ({
    getSnapshot: mocks.getSnapshot,
    subscribe: (listener: () => void) => {
      mocks.listeners.add(listener);
      return () => {
        mocks.listeners.delete(listener);
      };
    },
  }),
}));
vi.mock('./chat-queries', () => ({
  useChatApi: () => mocks,
  chatKeys: {
    conversation: (user: string, id: string) => ['chat', user, 'conversation', id],
    history: (user: string, id: string, offset: number) => [
      'chat',
      user,
      'conversation',
      id,
      'history',
      offset,
    ],
  },
}));
vi.mock('./response-feedback-target', () => ({
  rememberResponseFeedbackTarget: vi.fn(),
}));
vi.mock('./customer-escalation-query', () => ({
  customerEscalationKey: (user: string, id: string) => ['support', user, id],
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
const reply = {
  ok: true as const,
  data: { customer_message_id: 'saved-customer-message', succeeded: true },
};
const clients: QueryClient[] = [];
function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const wrapper = ({ children }: { readonly children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(
    () =>
      useChatSubmission({
        conversationId: 'conversation-1',
        onPageChange: vi.fn(),
      }),
    { wrapper },
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.getSnapshot.mockReturnValue(mocks.session);
  mocks.get.mockResolvedValue({ ok: true, data: {} });
  mocks.history.mockResolvedValue({
    ok: true,
    data: {
      items: [{ message_id: 'saved-customer-message' }],
      total: 1,
      has_more: false,
    },
  });
});
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  mocks.listeners.clear();
});

describe('immediate message submission', () => {
  it('publishes a bubble while POST is unresolved and reconciles by saved ID', async () => {
    const pending = deferred<typeof reply>();
    mocks.send.mockReturnValue(pending.promise);
    const { result } = setup();
    let send!: ReturnType<typeof result.current.send>;
    act(() => {
      send = result.current.send('Hello');
    });
    expect(result.current.outgoing?.content).toBe('Hello');
    expect(result.current.outgoing?.phase).toBe('sending');
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    await act(async () => {
      pending.resolve(reply);
      await send;
    });
    expect(result.current.outgoing?.messageId).toBe('saved-customer-message');
    await act(async () => {
      await result.current.reconcile();
    });
    expect(result.current.outgoing).toBeNull();
    expect(mocks.send).toHaveBeenCalledTimes(1);
  });

  it('keeps an uncertain receipt and never retries the POST while reconciling', async () => {
    mocks.send.mockRejectedValue(new Error('offline'));
    const { result } = setup();
    await act(async () => {
      await result.current.send('Keep this visible').catch(() => undefined);
    });
    expect(result.current.outgoing?.phase).toBe('uncertain');
    await act(async () => {
      await result.current.reconcile();
    });
    expect(result.current.outgoing?.content).toBe('Keep this visible');
    expect(mocks.send).toHaveBeenCalledTimes(1);
  });

  it('stops loading and preserves a confirmed receipt when history fails', async () => {
    mocks.send.mockResolvedValue(reply);
    mocks.history.mockRejectedValue(new Error('read failed'));
    const { result } = setup();
    await act(async () => {
      await result.current.send('Hello');
    });
    await act(async () => {
      expect(await result.current.reconcile()).toBe(false);
    });
    expect(result.current.outgoing?.phase).toBe('saved');
    expect(result.current.outgoing?.content).toBe('Hello');
  });

  it('clears private pending text on session change and ignores a late response', async () => {
    const pending = deferred<typeof reply>();
    mocks.send.mockReturnValue(pending.promise);
    const { result } = setup();
    let send!: Promise<unknown>;
    act(() => {
      send = result.current.send('Private text').catch(() => undefined);
    });
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    act(() => {
      mocks.getSnapshot.mockReturnValue({
        ...mocks.session,
        phase: 'anonymous',
      });
      mocks.listeners.forEach((listener) => listener());
    });
    expect(result.current.outgoing).toBeNull();
    await act(async () => {
      pending.resolve(reply);
      await send;
    });
    expect(result.current.outgoing).toBeNull();
  });
});
