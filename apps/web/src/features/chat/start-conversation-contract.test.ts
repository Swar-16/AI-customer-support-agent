import { describe, expect, it } from 'vitest';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResponseContext } from '../../shared/api/transport';

import { decodeMessagePage } from './chat-contract';
import { decodeStartConversation } from './start-conversation-contract';

const CONVERSATION_ID = '11111111-1111-4111-8111-111111111111';
const CUSTOMER_MESSAGE_ID = '22222222-2222-4222-8222-222222222222';
const ASSISTANT_MESSAGE_ID = '33333333-3333-4333-8333-333333333333';
const RUN_ID = '44444444-4444-4444-8444-444444444444';
const TRACE_ID = '55555555-5555-4555-8555-555555555555';
const START_ID = '66666666-6666-4666-8666-666666666666';
const ESCALATION_ID = '77777777-7777-4777-8777-777777777777';
const FEEDBACK_ID = '88888888-8888-4888-8888-888888888888';
const TIMESTAMP = '2026-09-18T12:00:00Z';

function context(status: number, retryAfterMs: number | null = null): TransportResponseContext {
  return { status, retryAfterMs, traceId: TRACE_ID };
}

function answer(overrides: Record<string, unknown> = {}) {
  return {
    conversation_id: CONVERSATION_ID,
    customer_message_id: CUSTOMER_MESSAGE_ID,
    assistant_message_id: ASSISTANT_MESSAGE_ID,
    ai_run_id: RUN_ID,
    trace_id: TRACE_ID,
    start_request_id: START_ID,
    pipeline_stage: 'guardrails_completed',
    succeeded: true,
    idempotency_status: 'completed',
    created: true,
    replayed: false,
    response: 'How can I help?',
    escalation_id: null,
    failure_code: null,
    failure_retryable: null,
    ...overrides,
  };
}

function messagePage(overrides: Record<string, unknown> = {}) {
  return {
    items: [
      {
        message_id: ASSISTANT_MESSAGE_ID,
        conversation_id: CONVERSATION_ID,
        role: 'assistant',
        content: 'How can I help?',
        sequence_number: 2,
        created_at: TIMESTAMP,
        ...overrides,
      },
    ],
    total: 1,
    count: 1,
    limit: 50,
    offset: 0,
    has_more: false,
    next_offset: null,
  };
}

describe('start conversation response boundary', () => {
  it('accepts a newly created approved answer', () => {
    expect(decodeStartConversation(answer(), context(201))).toMatchObject({
      kind: 'terminal',
      outcome: 'answer',
      data: { conversation_id: CONVERSATION_ID, created: true },
    });
  });

  it('accepts a replay without creating another conversation', () => {
    expect(
      decodeStartConversation(answer({ created: false, replayed: true }), context(200)),
    ).toMatchObject({
      kind: 'terminal',
      outcome: 'answer',
      data: { created: false, replayed: true },
    });
  });

  it('accepts resumed processing that was not a terminal replay', () => {
    expect(
      decodeStartConversation(answer({ created: false, replayed: false }), context(200)),
    ).toMatchObject({
      kind: 'terminal',
      outcome: 'answer',
    });
  });

  it.each([
    [null, 2_000],
    [1_000, 2_000],
    [5_000, 5_000],
  ])('respects processing delays with header %s', (headerDelay, expectedDelay) => {
    const result = decodeStartConversation(
      {
        start_request_id: START_ID,
        conversation_id: CONVERSATION_ID,
        idempotency_status: 'processing',
        retry_after_seconds: 2,
      },
      context(202, headerDelay),
    );

    expect(result).toMatchObject({
      kind: 'processing',
      retryAfterMs: expectedDelay,
    });
  });

  it('accepts an escalation without inventing an assistant response', () => {
    const result = decodeStartConversation(
      answer({
        pipeline_stage: 'escalated',
        assistant_message_id: null,
        response: null,
        escalation_id: ESCALATION_ID,
      }),
      context(201),
    );

    expect(result).toMatchObject({
      kind: 'terminal',
      outcome: 'escalated',
      data: { response: null, escalation_id: ESCALATION_ID },
    });
  });

  it('preserves accepted failure identifiers', () => {
    const result = decodeStartConversation(
      answer({
        succeeded: false,
        pipeline_stage: 'failed',
        idempotency_status: 'failed',
        assistant_message_id: null,
        response: null,
        failure_code: 'TEST_FAILURE',
        failure_retryable: true,
      }),
      context(201),
    );

    expect(result).toMatchObject({
      kind: 'terminal',
      outcome: 'failed',
      data: {
        conversation_id: CONVERSATION_ID,
        customer_message_id: CUSTOMER_MESSAGE_ID,
        failure_retryable: true,
      },
    });
  });

  it.each([
    { pipeline_stage: 'unknown_future_stage' },
    { response: null },
    { response: '   ' },
    { escalation_id: ESCALATION_ID },
    { failure_code: 'TEST_FAILURE' },
    { created: false },
    { replayed: true },
  ])('rejects contradictory or unsupported results: %j', (overrides) => {
    expect(() => decodeStartConversation(answer(overrides), context(201))).toThrow(SafeApiError);
  });

  it('rejects a terminal body sent with processing status', () => {
    expect(() => decodeStartConversation(answer(), context(202))).toThrow(SafeApiError);
  });

  it('rejects an unexpected success status', () => {
    expect(() => decodeStartConversation(answer(), context(204))).toThrow(SafeApiError);
  });

  it('strips unapproved response fields', () => {
    const result = decodeStartConversation(answer({ internal_debug: 'excluded' }), context(201));

    expect(result.data).not.toHaveProperty('internal_debug');
  });
});

describe('historical feedback boundary', () => {
  it('preserves eligible provenance and a saved rating', () => {
    const page = decodeMessagePage(
      messagePage({
        ai_run_id: RUN_ID,
        feedback_eligible: true,
        feedback: {
          feedback_id: FEEDBACK_ID,
          rating: 4,
          helpful: true,
          created_at: TIMESTAMP,
          review_notes: 'excluded',
        },
      }),
    );

    expect(page.items[0]).toMatchObject({
      ai_run_id: RUN_ID,
      feedback_eligible: true,
      feedback: {
        feedback_id: FEEDBACK_ID,
        rating: 4,
        helpful: true,
      },
    });
    expect(page.items[0]?.feedback).not.toHaveProperty('review_notes');
  });

  it('defaults missing provenance to ineligible', () => {
    const page = decodeMessagePage(messagePage());

    expect(page.items[0]).toMatchObject({
      ai_run_id: null,
      feedback_eligible: false,
      feedback: null,
    });
  });

  it('preserves existing feedback even when new feedback is ineligible', () => {
    const page = decodeMessagePage(
      messagePage({
        ai_run_id: null,
        feedback_eligible: false,
        feedback: {
          feedback_id: FEEDBACK_ID,
          rating: 3,
          created_at: TIMESTAMP,
        },
      }),
    );

    expect(page.items[0]).toMatchObject({
      feedback_eligible: false,
      feedback: { rating: 3, helpful: null },
    });
  });

  it('rejects an invalid saved rating', () => {
    expect(() =>
      decodeMessagePage(
        messagePage({
          feedback: {
            feedback_id: FEEDBACK_ID,
            rating: 6,
            created_at: TIMESTAMP,
          },
        }),
      ),
    ).toThrow(SafeApiError);
  });
});
