import { describe, expect, it, vi } from 'vitest';

import { SafeApiError } from '../../shared/api/safe-error';
import { createTransport } from '../../shared/api/transport';
import { createChatApi } from './chat-api';
import { customerMessageSchema, decodeSendMessage, type SendMessageResult } from './chat-contract';

const CONVERSATION_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';
const CUSTOMER_MESSAGE_ID = 'bf187e45-c833-444b-bcc5-39465b2be9fc';
const ASSISTANT_MESSAGE_ID = '256c6cb2-f5da-4e50-a66f-539f78031887';
const RUN_ID = '2d125622-c20c-4f40-846c-4f6587b9e368';
const TRACE_ID = '77b7f548-b319-47a5-8a04-0cb67fef70d0';
const ESCALATION_ID = '458890db-2435-4267-895d-9aa795dcd8cb';

function response(overrides: Partial<SendMessageResult> = {}): SendMessageResult {
  return {
    conversation_id: CONVERSATION_ID,
    customer_message_id: CUSTOMER_MESSAGE_ID,
    ai_run_id: RUN_ID,
    trace_id: TRACE_ID,
    pipeline_stage: 'guardrails_completed',
    intent: null,
    decision: null,
    assistant_message_id: ASSISTANT_MESSAGE_ID,
    escalation_id: null,
    response: 'Here is the information you requested.',
    succeeded: true,
    ...overrides,
  };
}

function setup() {
  const fetchImpl = vi.fn<typeof fetch>();
  const transport = createTransport({
    apiOrigin: 'https://api.example.test',
    getAccessToken: () => 'test-only-token',
    fetchImpl,
  });

  return { api: createChatApi(transport), fetchImpl };
}

describe('customer message validation', () => {
  it('normalizes surrounding whitespace and rejects blank input', () => {
    expect(customerMessageSchema.parse('  Order question\n')).toBe('Order question');
    expect(customerMessageSchema.safeParse(' \n\t ').success).toBe(false);
  });

  it('counts Unicode code points for the backend character limit', () => {
    expect(customerMessageSchema.safeParse('😀'.repeat(20_000)).success).toBe(true);
    expect(customerMessageSchema.safeParse('😀'.repeat(20_001)).success).toBe(false);
  });
});

describe('send response boundary', () => {
  it('strips fields outside the response allowlist', () => {
    const decoded = decodeSendMessage({
      ...response(),
      internal_debug: 'must not survive adaptation',
    });

    expect(decoded).not.toHaveProperty('internal_debug');
    expect(decoded.assistant_message_id).toBe(ASSISTANT_MESSAGE_ID);
  });

  it('accepts a confirmed escalation without inventing an assistant reply', () => {
    const decoded = decodeSendMessage(
      response({
        pipeline_stage: 'escalated',
        assistant_message_id: null,
        response: null,
        escalation_id: ESCALATION_ID,
      }),
    );

    expect(decoded.succeeded).toBe(true);
    expect(decoded.response).toBeNull();
    expect(decoded.escalation_id).toBe(ESCALATION_ID);
  });

  it('accepts omitted optional fields without fabricating response text', () => {
    const decoded = decodeSendMessage({
      conversation_id: CONVERSATION_ID,
      customer_message_id: CUSTOMER_MESSAGE_ID,
      ai_run_id: RUN_ID,
      trace_id: TRACE_ID,
      pipeline_stage: 'decision_completed',
      succeeded: true,
    });

    expect(decoded.response).toBeNull();
    expect(decoded.assistant_message_id).toBeNull();
    expect(decoded.escalation_id).toBeNull();
  });

  it('rejects response text without its persisted message identifier', () => {
    expect(() => decodeSendMessage(response({ assistant_message_id: null }))).toThrow(SafeApiError);
  });

  it('rejects a persisted message identifier without response text', () => {
    expect(() => decodeSendMessage(response({ response: null }))).toThrow(SafeApiError);
  });
});

describe('Chat send adapter', () => {
  it('posts only the normalized message to the selected conversation', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(
      Response.json(response(), {
        headers: { 'X-Trace-ID': TRACE_ID },
      }),
    );

    const result = await api.send(CONVERSATION_ID, '  Order question\n');

    expect(fetchImpl).toHaveBeenCalledTimes(1);

    const call = fetchImpl.mock.calls[0];
    if (!call) throw new Error('Expected one request.');

    expect(String(call[0])).toBe(
      `https://api.example.test/v1/conversations/${CONVERSATION_ID}/messages`,
    );
    expect(call[1]?.method).toBe('POST');
    expect(call[1]?.credentials).toBe('omit');
    expect(call[1]?.body).toBe(JSON.stringify({ message: 'Order question' }));

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error('Expected successful adaptation.');

    expect(result.data.customer_message_id).toBe(CUSTOMER_MESSAGE_ID);
    expect(result.traceId).toBe(TRACE_ID);
  });

  it('rejects invalid input before making a request', async () => {
    const { api, fetchImpl } = setup();

    expect((await api.send('invalid-id', 'Question')).ok).toBe(false);
    expect((await api.send(CONVERSATION_ID, '   ')).ok).toBe(false);
    expect((await api.send(CONVERSATION_ID, 'a'.repeat(20_001))).ok).toBe(false);

    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('rejects a response belonging to another conversation', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(response({ conversation_id: RUN_ID })));

    const result = await api.send(CONVERSATION_ID, 'Question');

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected rejected response.');

    expect(result.error.kind).toBe('invalid-response');
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it.each([401, 403, 409, 413, 415, 422, 500, 503, 504])(
    'does not retry HTTP %i',
    async (status) => {
      const { api, fetchImpl } = setup();
      fetchImpl.mockResolvedValue(
        Response.json({ error: { code: 'TEST_ERROR', message: 'Test failure.' } }, { status }),
      );

      const result = await api.send(CONVERSATION_ID, 'Question');

      expect(result.ok).toBe(false);
      if (result.ok) throw new Error('Expected HTTP failure.');

      expect(result.error.status).toBe(status);
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    },
  );

  it('does not resend after a network failure', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockRejectedValue(new Error('Simulated connection loss'));

    const result = await api.send(CONVERSATION_ID, 'Question');

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected network failure.');

    expect(result.error.kind).toBe('network');
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('does not send when the caller has already cancelled', async () => {
    const { api, fetchImpl } = setup();
    const controller = new AbortController();
    controller.abort();

    const result = await api.send(CONVERSATION_ID, 'Question', controller.signal);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected cancellation.');

    expect(result.error.kind).toBe('aborted');
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
