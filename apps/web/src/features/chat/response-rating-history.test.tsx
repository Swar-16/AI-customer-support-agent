// apps/web/src/features/chat/response-rating-history.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { components } from '../../shared/api/generated/schema';
import { createTransport } from '../../shared/api/transport';
import { TransportContext } from '../../shared/api/transport-context';

import { ResponseRating } from './response-rating';

const mocks = vi.hoisted(() => {
  const snapshot = {
    phase: 'authenticated',
    user: {
      id: '99999999-9999-4999-8999-999999999999',
      role: 'customer',
      status: 'active',
    },
  };

  const controller = {
    getSnapshot: () => snapshot,
  };

  return {
    snapshot,
    controller,
    target: vi.fn<
      () => {
        conversationId: string;
        responseMessageId: string;
        aiRunId: string;
      } | null
    >(),
  };
});

vi.mock('../../shared/auth/session-context', () => ({
  useSession: () => mocks.snapshot,
  useSessionController: () => mocks.controller,
}));

vi.mock('./response-feedback-target', () => ({
  useResponseFeedbackTarget: () => mocks.target(),
}));

type Message = components['schemas']['ConversationMessageResponse'];

const CONVERSATION_ID = '11111111-1111-4111-8111-111111111111';
const MESSAGE_ID = '22222222-2222-4222-8222-222222222222';
const RUN_ID = '33333333-3333-4333-8333-333333333333';
const FEEDBACK_ID = '44444444-4444-4444-8444-444444444444';
const TIMESTAMP = '2026-09-18T12:00:00Z';

function message(overrides: Partial<Message> = {}): Message {
  return {
    message_id: MESSAGE_ID,
    conversation_id: CONVERSATION_ID,
    role: 'assistant',
    content: 'A synthetic test response.',
    sequence_number: 2,
    created_at: TIMESTAMP,
    ai_run_id: RUN_ID,
    feedback_eligible: true,
    feedback: null,
    ...overrides,
  };
}

const clients: QueryClient[] = [];

function renderRating(initialMessage: Message) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  clients.push(client);

  const fetchImpl = vi.fn<typeof fetch>();
  fetchImpl.mockRejectedValue(new Error('Unexpected test request.'));

  const transport = createTransport({
    apiOrigin: 'https://api.example.test',
    getAccessToken: () => 'synthetic-test-token',
    fetchImpl,
  });

  function tree(currentMessage: Message) {
    return (
      <QueryClientProvider client={client}>
        <TransportContext.Provider value={transport}>
          <ResponseRating
            conversationId={CONVERSATION_ID}
            responseMessageId={MESSAGE_ID}
            message={currentMessage}
          />
        </TransportContext.Provider>
      </QueryClientProvider>
    );
  }

  const view = render(tree(initialMessage));

  return {
    fetchImpl,
    updateMessage(next: Message) {
      view.rerender(tree(next));
    },
  };
}

beforeEach(() => {
  mocks.target.mockReset();
  mocks.target.mockReturnValue(null);
});

afterEach(() => {
  cleanup();

  for (const client of clients) {
    client.clear();
  }

  clients.length = 0;
});

describe('response rating from server history', () => {
  it('restores saved stars without a locally cached feedback target', () => {
    const { fetchImpl } = renderRating(
      message({
        feedback: {
          feedback_id: FEEDBACK_ID,
          rating: 4,
          helpful: true,
          created_at: TIMESTAMP,
        },
      }),
    );

    expect(screen.getByText('Your rating: 4 out of 5. Thank you.')).toBeInTheDocument();

    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /submit rating/i })).not.toBeInTheDocument();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('offers feedback for an eligible historical answer without a cached target', () => {
    const { fetchImpl } = renderRating(message());

    expect(screen.getByRole('form', { name: 'Rate this response' })).toBeInTheDocument();

    expect(screen.getAllByRole('radio')).toHaveLength(5);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('does not let cached eligibility override ineligible server history', () => {
    mocks.target.mockReturnValue({
      conversationId: CONVERSATION_ID,
      responseMessageId: MESSAGE_ID,
      aiRunId: RUN_ID,
    });

    const { fetchImpl } = renderRating(
      message({
        feedback_eligible: false,
        ai_run_id: null,
      }),
    );

    expect(screen.queryByRole('form', { name: 'Rate this response' })).not.toBeInTheDocument();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('shows an existing rating even if new feedback is ineligible', () => {
    renderRating(
      message({
        feedback_eligible: false,
        ai_run_id: null,
        feedback: {
          feedback_id: FEEDBACK_ID,
          rating: 3,
          helpful: null,
          created_at: TIMESTAMP,
        },
      }),
    );

    expect(screen.getByText('Your rating: 3 out of 5. Thank you.')).toBeInTheDocument();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
  });

  it('replaces the form with the rating returned by refreshed history', () => {
    const { updateMessage, fetchImpl } = renderRating(message());

    expect(screen.getByRole('form', { name: 'Rate this response' })).toBeInTheDocument();

    updateMessage(
      message({
        feedback: {
          feedback_id: FEEDBACK_ID,
          rating: 2,
          helpful: false,
          created_at: TIMESTAMP,
        },
      }),
    );

    expect(screen.getByText('Your rating: 2 out of 5. Thank you.')).toBeInTheDocument();

    expect(screen.queryByRole('form', { name: 'Rate this response' })).not.toBeInTheDocument();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('does not render feedback for a mismatched message', () => {
    renderRating(
      message({
        message_id: '55555555-5555-4555-8555-555555555555',
      }),
    );

    expect(screen.queryByRole('form', { name: 'Rate this response' })).not.toBeInTheDocument();

    expect(screen.queryByRole('region', { name: 'Saved response rating' })).not.toBeInTheDocument();
  });
});
