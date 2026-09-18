// apps/web/src/features/chat/conversation-draft.test.tsx
import { StrictMode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { TransportContext } from '../../shared/api/transport-context';
import { ConversationDraft } from './conversation-draft';

const sessionMock = vi.hoisted(() => {
  const listeners = new Set<() => void>();

  const initialSnapshot = {
    phase: 'authenticated',
    user: {
      id: '99999999-9999-4999-8999-999999999999',
      role: 'customer',
      status: 'active',
    },
  };

  let snapshot = initialSnapshot;

  const controller = {
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };

  return {
    controller,
    reset() {
      listeners.clear();
      snapshot = initialSnapshot;
    },
    endSession() {
      snapshot = { ...initialSnapshot, phase: 'anonymous' };
      for (const listener of listeners) {
        listener();
      }
    },
  };
});

vi.mock('../../shared/auth/session-context', () => ({
  useSessionController: () => sessionMock.controller,
}));

const CONVERSATION_ID = '11111111-1111-4111-8111-111111111111';
const START_ID = '22222222-2222-4222-8222-222222222222';
const CUSTOMER_MESSAGE_ID = '33333333-3333-4333-8333-333333333333';
const ASSISTANT_MESSAGE_ID = '44444444-4444-4444-8444-444444444444';
const RUN_ID = '55555555-5555-4555-8555-555555555555';
const TRACE_ID = '66666666-6666-4666-8666-666666666666';

function jsonResponse(value: unknown, status: number) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      'Content-Type': 'application/json',
    },
  });
}

function answerResponse(replayed = false) {
  return jsonResponse(
    {
      conversation_id: CONVERSATION_ID,
      start_request_id: START_ID,
      customer_message_id: CUSTOMER_MESSAGE_ID,
      assistant_message_id: ASSISTANT_MESSAGE_ID,
      ai_run_id: RUN_ID,
      trace_id: TRACE_ID,
      pipeline_stage: 'guardrails_completed',
      response: 'How can I help?',
      succeeded: true,
      idempotency_status: 'completed',
      created: !replayed,
      replayed,
    },
    replayed ? 200 : 201,
  );
}

function processingResponse() {
  return jsonResponse(
    {
      conversation_id: CONVERSATION_ID,
      start_request_id: START_ID,
      idempotency_status: 'processing',
      retry_after_seconds: 2,
    },
    202,
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });

  return { promise, resolve };
}

function SavedConversation() {
  const { conversationId } = useParams();

  return (
    <main>
      <h1>Saved conversation</h1>
      <p>{conversationId}</p>
    </main>
  );
}

const clients: QueryClient[] = [];

function renderDraft(fetchImpl: typeof fetch) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  clients.push(queryClient);

  const request = createTransport({
    apiOrigin: 'https://api.example.test',
    getAccessToken: () => 'synthetic-test-token',
    fetchImpl,
  });

  return render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <TransportContext.Provider value={request}>
          <MemoryRouter initialEntries={['/chat?draft=1']}>
            <Routes>
              <Route path="/chat" element={<ConversationDraft onRequestLeave={() => {}} />} />
              <Route path="/chat/:conversationId" element={<SavedConversation />} />
            </Routes>
          </MemoryRouter>
        </TransportContext.Provider>
      </QueryClientProvider>
    </StrictMode>,
  );
}

function submitMessage(message = 'Hello') {
  fireEvent.change(screen.getByRole('textbox', { name: 'Your message' }), {
    target: { value: message },
  });

  fireEvent.submit(screen.getByRole('form', { name: 'Start a conversation' }));
}

beforeEach(() => {
  sessionMock.reset();
});

afterEach(() => {
  cleanup();

  for (const client of clients) {
    client.clear();
  }
  clients.length = 0;

  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('conversation draft', () => {
  it('does not create a conversation when the draft opens', () => {
    const fetchImpl = vi.fn<typeof fetch>();

    renderDraft(fetchImpl);

    expect(
      screen.getByRole('heading', {
        name: 'What can we help you with?',
      }),
    ).toBeInTheDocument();

    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('sends once, clears the composer, and opens the saved conversation', async () => {
    const pending = deferred<Response>();
    const fetchImpl = vi.fn<typeof fetch>();
    fetchImpl.mockReturnValueOnce(pending.promise);

    renderDraft(fetchImpl);
    submitMessage();

    // Even a second programmatic form submission must not send again.
    fireEvent.submit(screen.getByRole('form', { name: 'Start a conversation' }));

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('textbox', { name: 'Your message' })).toHaveValue('');

    await act(async () => {
      pending.resolve(answerResponse());
    });

    expect(await screen.findByRole('heading', { name: 'Saved conversation' })).toBeInTheDocument();
    expect(screen.getByText(CONVERSATION_ID)).toBeInTheDocument();
  });

  it('waits before checking a processing request and preserves its key and body', async () => {
    vi.useFakeTimers();

    const fetchImpl = vi.fn<typeof fetch>();
    fetchImpl.mockResolvedValueOnce(processingResponse());
    fetchImpl.mockResolvedValueOnce(answerResponse(true));

    renderDraft(fetchImpl);

    await act(async () => {
      submitMessage('  Hello  ');
    });

    expect(
      screen.getByRole('button', {
        name: 'Please wait before checking',
      }),
    ).toBeDisabled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_999);
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Check again' }));
    });

    expect(fetchImpl).toHaveBeenCalledTimes(2);

    const first = fetchImpl.mock.calls[0]?.[1];
    const second = fetchImpl.mock.calls[1]?.[1];

    const firstKey = new Headers(first?.headers).get('Idempotency-Key');
    const secondKey = new Headers(second?.headers).get('Idempotency-Key');

    expect(firstKey).toMatch(/^[!-~]{16,255}$/u);
    expect(secondKey).toBe(firstKey);
    expect(second?.body).toBe(first?.body);

    expect(screen.getByRole('heading', { name: 'Saved conversation' })).toBeInTheDocument();
  });

  it('shows an accepted failure and opens the existing conversation on request', async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    fetchImpl.mockResolvedValueOnce(
      jsonResponse(
        {
          conversation_id: CONVERSATION_ID,
          start_request_id: START_ID,
          customer_message_id: CUSTOMER_MESSAGE_ID,
          ai_run_id: RUN_ID,
          trace_id: TRACE_ID,
          pipeline_stage: 'failed',
          succeeded: false,
          idempotency_status: 'failed',
          created: true,
          replayed: false,
          failure_code: 'TEST_FAILURE',
          failure_retryable: true,
        },
        201,
      ),
    );

    renderDraft(fetchImpl);
    submitMessage();

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Your conversation and message were saved',
    );

    fireEvent.click(screen.getByRole('button', { name: 'Open saved conversation' }));

    expect(await screen.findByRole('heading', { name: 'Saved conversation' })).toBeInTheDocument();

    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('cancels on session change and ignores a late success', async () => {
    const pending = deferred<Response>();
    const fetchImpl = vi.fn<typeof fetch>();
    fetchImpl.mockReturnValueOnce(pending.promise);

    renderDraft(fetchImpl);
    submitMessage();

    const signal = fetchImpl.mock.calls[0]?.[1]?.signal;

    act(() => {
      sessionMock.endSession();
    });

    expect(signal?.aborted).toBe(true);

    await act(async () => {
      pending.resolve(answerResponse());
    });

    await waitFor(() => {
      expect(screen.getByText('Your session changed. Please sign in again.')).toBeInTheDocument();
    });

    expect(screen.queryByRole('heading', { name: 'Saved conversation' })).not.toBeInTheDocument();
  });
});
