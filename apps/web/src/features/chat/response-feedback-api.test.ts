// apps/web/src/features/chat/response-feedback-api.test.ts
import { describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { createResponseFeedbackApi, type RatingInput } from './response-feedback-api';

const CONVERSATION_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';
const MESSAGE_ID = '256c6cb2-f5da-4e50-a66f-539f78031887';
const RUN_ID = '2d125622-c20c-4f40-846c-4f6587b9e368';
const CUSTOMER_ID = 'bf187e45-c833-444b-bcc5-39465b2be9fc';
const FEEDBACK_ID = '458890db-2435-4267-895d-9aa795dcd8cb';

function input(rating = 4): RatingInput {
  return {
    response_message_id: MESSAGE_ID,
    ai_run_id: RUN_ID,
    rating,
  };
}

function receipt(created = true) {
  return {
    feedback_id: FEEDBACK_ID,
    conversation_id: CONVERSATION_ID,
    customer_id: CUSTOMER_ID,
    response_message_id: MESSAGE_ID,
    ai_run_id: RUN_ID,
    rating: 4,
    helpful: null,
    comment: null,
    reason_codes: [],
    status: 'pending',
    row_version: 1,
    created,
  };
}

function setup() {
  const fetchImpl = vi.fn<typeof fetch>();

  const api = createResponseFeedbackApi(
    createTransport({
      apiOrigin: 'https://api.example.test',
      getAccessToken: () => 'test-only-token',
      fetchImpl,
    }),
  );

  return { api, fetchImpl };
}

describe('Response feedback API', () => {
  it('submits only the required rating fields', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(receipt(), { status: 201 }));

    const extendedInput = {
      ...input(),
      customer_id: CUSTOMER_ID,
      metadata: { unrestricted: 'must-not-be-sent' },
    };

    const result = await api.submitRating(CONVERSATION_ID, extendedInput);

    expect(result.ok).toBe(true);

    const call = fetchImpl.mock.calls[0];
    if (!call) throw new Error('Expected one request.');

    expect(String(call[0])).toBe(
      `https://api.example.test/v1/conversations/${CONVERSATION_ID}/feedback`,
    );
    expect(call[1]?.method).toBe('POST');
    expect(call[1]?.body).toBe(JSON.stringify(input()));
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it.each([true, false])('accepts confirmed feedback with created=%s', async (created) => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(receipt(created), { status: 201 }));

    const result = await api.submitRating(CONVERSATION_ID, input());

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error('Expected confirmed feedback.');

    expect(result.data.created).toBe(created);
    expect(result.data.rating).toBe(4);
  });

  it.each([0, 6, 1.5, Number.NaN])('rejects invalid rating %s without sending', async (rating) => {
    const { api, fetchImpl } = setup();

    const result = await api.submitRating(CONVERSATION_ID, input(rating));

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('rejects invalid provenance identifiers locally', async () => {
    const { api, fetchImpl } = setup();

    const result = await api.submitRating(CONVERSATION_ID, {
      ...input(),
      ai_run_id: 'unknown',
    });

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it.each([
    { conversation_id: FEEDBACK_ID },
    { response_message_id: FEEDBACK_ID },
    { ai_run_id: FEEDBACK_ID },
    { ai_run_id: null },
    { rating: 2 },
    { status: 'unknown' },
    { row_version: 0 },
  ])('rejects a mismatched or invalid receipt: %j', async (override) => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json({ ...receipt(), ...override }, { status: 201 }));

    const result = await api.submitRating(CONVERSATION_ID, input());

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected rejected receipt.');

    expect(result.error.kind).toBe('invalid-response');
  });

  it('returns only the receipt allowlist', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(
      Response.json(
        {
          ...receipt(),
          metadata: { internal: 'discard-me' },
          review_notes: 'discard-me',
        },
        { status: 201 },
      ),
    );

    const result = await api.submitRating(CONVERSATION_ID, input());

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error('Expected confirmed feedback.');

    expect(Object.keys(result.data).sort()).toEqual(
      [
        'feedback_id',
        'conversation_id',
        'customer_id',
        'response_message_id',
        'ai_run_id',
        'rating',
        'status',
        'row_version',
        'created',
      ].sort(),
    );
  });

  it('preserves a conflict without treating it as success or retrying', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockResolvedValue(
      Response.json(
        {
          error: {
            code: 'TEST_CONFLICT',
            message: 'Feedback differs.',
          },
        },
        { status: 409 },
      ),
    );

    const result = await api.submitRating(CONVERSATION_ID, input());

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected conflict.');

    expect(result.error.status).toBe(409);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('does not retry an uncertain submission', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockRejectedValue(new Error('Simulated connection loss'));

    const result = await api.submitRating(CONVERSATION_ID, input());

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected network failure.');

    expect(result.error.kind).toBe('network');
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('does not send an already-cancelled submission', async () => {
    const { api, fetchImpl } = setup();
    const controller = new AbortController();
    controller.abort();

    const result = await api.submitRating(CONVERSATION_ID, input(), controller.signal);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected cancellation.');

    expect(result.error.kind).toBe('aborted');
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
