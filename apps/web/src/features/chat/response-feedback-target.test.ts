// apps/web/src/features/chat/response-feedback-target.test.ts
import { QueryClient } from '@tanstack/react-query';
import { afterEach, describe, expect, it } from 'vitest';

import type { SendMessageResult } from './chat-contract';
import {
  rememberResponseFeedbackTarget,
  responseFeedbackTargetKey,
} from './response-feedback-target';

const customerId = '00000000-0000-4000-8000-000000000001';
const otherCustomerId = '00000000-0000-4000-8000-000000000002';
const conversationId = '00000000-0000-4000-8000-000000000003';
const otherConversationId = '00000000-0000-4000-8000-000000000004';
const responseMessageId = '00000000-0000-4000-8000-000000000005';
const aiRunId = '00000000-0000-4000-8000-000000000006';

const clients: QueryClient[] = [];

function createClient() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  clients.push(client);
  return client;
}

function createResult(overrides: Partial<SendMessageResult> = {}): SendMessageResult {
  return {
    conversation_id: conversationId,
    customer_message_id: '00000000-0000-4000-8000-000000000007',
    ai_run_id: aiRunId,
    trace_id: '00000000-0000-4000-8000-000000000008',
    pipeline_stage: 'completed',
    intent: null,
    decision: null,
    assistant_message_id: responseMessageId,
    escalation_id: null,
    response: 'Synthetic assistant response.',
    succeeded: true,
    ...overrides,
  };
}

afterEach(() => {
  for (const client of clients) client.clear();
  clients.length = 0;
});

describe('response feedback targets', () => {
  it('stores only the confirmed identifiers, without response content', () => {
    const client = createClient();

    rememberResponseFeedbackTarget(client, customerId, conversationId, createResult());

    expect(
      client.getQueryData(responseFeedbackTargetKey(customerId, conversationId, responseMessageId)),
    ).toEqual({
      conversationId,
      responseMessageId,
      aiRunId,
    });
  });

  it.each([
    {
      name: 'failed pipeline',
      overrides: { succeeded: false },
    },
    {
      name: 'missing assistant response',
      overrides: { assistant_message_id: null, response: null },
    },
    {
      name: 'blank response',
      overrides: { response: '   ' },
    },
    {
      name: 'another conversation',
      overrides: { conversation_id: otherConversationId },
    },
  ] satisfies Array<{
    name: string;
    overrides: Partial<SendMessageResult>;
  }>)('does not enable feedback for $name', ({ overrides }) => {
    const client = createClient();

    rememberResponseFeedbackTarget(client, customerId, conversationId, createResult(overrides));

    expect(client.getQueryCache().getAll()).toHaveLength(0);
  });

  it('isolates associations by customer and conversation', () => {
    const client = createClient();

    rememberResponseFeedbackTarget(client, customerId, conversationId, createResult());

    expect(
      client.getQueryData(
        responseFeedbackTargetKey(otherCustomerId, conversationId, responseMessageId),
      ),
    ).toBeUndefined();

    expect(
      client.getQueryData(
        responseFeedbackTargetKey(customerId, otherConversationId, responseMessageId),
      ),
    ).toBeUndefined();
  });

  it('does not infer an association for historical messages', () => {
    const client = createClient();

    expect(
      client.getQueryData(responseFeedbackTargetKey(customerId, conversationId, responseMessageId)),
    ).toBeUndefined();
  });

  it('removes associations when session cleanup clears the Query client', () => {
    const client = createClient();

    rememberResponseFeedbackTarget(client, customerId, conversationId, createResult());

    client.clear();

    expect(
      client.getQueryData(responseFeedbackTargetKey(customerId, conversationId, responseMessageId)),
    ).toBeUndefined();
  });
});
