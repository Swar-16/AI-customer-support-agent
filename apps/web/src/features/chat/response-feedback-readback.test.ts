// apps/web/src/features/chat/response-feedback-readback.test.ts
import { describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { createResponseFeedbackReadback } from './response-feedback-readback';

function id(value: number): string {
  return `00000000-0000-4000-8000-${String(value).padStart(12, '0')}`;
}

const customerId = id(1);
const conversationId = id(2);
const responseMessageId = id(3);

function record(index = 0, matches = false) {
  return {
    feedback_id: id(1000 + index),
    conversation_id: conversationId,
    customer_id: customerId,
    response_message_id: matches ? responseMessageId : id(2000 + index),
    rating: 4,
    ai_run_id: id(4),
    helpful: null,
    comment: 'Synthetic comment that must not be returned.',
    reason_codes: [],
    status: 'pending',
    row_version: 1,
    created_at: '2026-09-15T10:00:00Z',
    updated_at: '2026-09-15T10:00:00Z',
    metadata: { internal: 'Synthetic metadata' },
    review_notes: 'Synthetic review information',
  };
}

function page(items: ReturnType<typeof record>[], offset = 0, hasMore = false) {
  return {
    items,
    count: items.length,
    limit: 100,
    offset,
    has_more: hasMore,
  };
}

function setup() {
  const fetchImpl = vi.fn<typeof fetch>();

  const transport = createTransport({
    apiOrigin: 'https://api.example.test',
    getAccessToken: () => 'test-only-token',
    fetchImpl,
  });

  return {
    fetchImpl,
    api: createResponseFeedbackReadback(transport),
  };
}

describe('feedback read-back', () => {
  it('uses only the supported customer filter and returns a safe projection', async () => {
    const { fetchImpl, api } = setup();

    fetchImpl.mockResolvedValue(Response.json(page([record(0, true)])));

    await expect(api.findRating(customerId, conversationId, responseMessageId)).resolves.toEqual({
      kind: 'found',
      feedbackId: id(1000),
      rating: 4,
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);

    const call = fetchImpl.mock.calls[0];
    expect(call).toBeDefined();

    if (!call) throw new Error('Expected a request');

    const url = new URL(String(call[0]));

    expect(url.pathname).toBe('/v1/feedback');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      conversation_id: conversationId,
      limit: '100',
      offset: '0',
    });
    expect(call[1]?.method).toBe('GET');
    expect(call[1]?.body).toBeUndefined();
  });

  it('finds a rating on the next page', async () => {
    const { fetchImpl, api } = setup();

    fetchImpl
      .mockResolvedValueOnce(
        Response.json(
          page(
            Array.from({ length: 100 }, (_, index) => record(index)),
            0,
            true,
          ),
        ),
      )
      .mockResolvedValueOnce(Response.json(page([record(100, true)], 100)));

    await expect(api.findRating(customerId, conversationId, responseMessageId)).resolves.toEqual({
      kind: 'found',
      feedbackId: id(1100),
      rating: 4,
    });

    expect(fetchImpl).toHaveBeenCalledTimes(2);

    const call = fetchImpl.mock.calls[1];
    expect(call).toBeDefined();

    if (!call) throw new Error('Expected a second request');

    expect(new URL(String(call[0])).searchParams.get('offset')).toBe('100');
  });

  it('reports not observed without claiming the mutation failed', async () => {
    const { fetchImpl, api } = setup();
    fetchImpl.mockResolvedValue(Response.json(page([])));

    await expect(api.findRating(customerId, conversationId, responseMessageId)).resolves.toEqual({
      kind: 'not-observed',
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('stops after five pages and reports an incomplete scan', async () => {
    const { fetchImpl, api } = setup();

    fetchImpl.mockImplementation(async (input) => {
      const offset = Number(new URL(String(input)).searchParams.get('offset'));

      return Response.json(
        page(
          Array.from({ length: 100 }, (_, index) => record(offset + index)),
          offset,
          true,
        ),
      );
    });

    await expect(api.findRating(customerId, conversationId, responseMessageId)).resolves.toEqual({
      kind: 'incomplete',
    });

    expect(fetchImpl).toHaveBeenCalledTimes(5);
    expect(fetchImpl.mock.calls.every((call) => call[1]?.method === 'GET')).toBe(true);
  });

  it.each([
    {
      name: 'another customer',
      body: page([{ ...record(0, true), customer_id: id(99) }]),
    },
    {
      name: 'another conversation',
      body: page([{ ...record(0, true), conversation_id: id(99) }]),
    },
    {
      name: 'incorrect count',
      body: { ...page([]), count: 1 },
    },
    {
      name: 'incorrect offset',
      body: page([], 100),
    },
    {
      name: 'empty page claiming more records',
      body: page([], 0, true),
    },
    {
      name: 'duplicate matching feedback',
      body: page([record(0, true), record(1, true)]),
    },
  ])('rejects $name', async ({ body }) => {
    const { fetchImpl, api } = setup();
    fetchImpl.mockResolvedValue(Response.json(body));

    await expect(
      api.findRating(customerId, conversationId, responseMessageId),
    ).rejects.toMatchObject({ kind: 'invalid-response' });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('preserves authorization failure and does not retry', async () => {
    const { fetchImpl, api } = setup();

    fetchImpl.mockResolvedValue(
      Response.json({ error: { code: 'FORBIDDEN', message: 'Not allowed' } }, { status: 403 }),
    );

    await expect(
      api.findRating(customerId, conversationId, responseMessageId),
    ).rejects.toMatchObject({ kind: 'http', status: 403 });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('does not turn a network failure into an empty result', async () => {
    const { fetchImpl, api } = setup();
    fetchImpl.mockRejectedValue(new Error('Synthetic failure'));

    await expect(
      api.findRating(customerId, conversationId, responseMessageId),
    ).rejects.toMatchObject({ kind: 'network' });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('does not request anything when already cancelled', async () => {
    const { fetchImpl, api } = setup();
    const controller = new AbortController();
    controller.abort();

    await expect(
      api.findRating(customerId, conversationId, responseMessageId, controller.signal),
    ).rejects.toMatchObject({ kind: 'aborted' });

    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('rejects invalid identifiers before requesting', async () => {
    const { fetchImpl, api } = setup();

    await expect(api.findRating(customerId, 'invalid', responseMessageId)).rejects.toMatchObject({
      kind: 'invalid-response',
    });

    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
