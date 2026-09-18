// apps/web/src/features/chat/start-conversation-api.test.ts
import { describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';

import { createStartConversationApi } from './start-conversation-api';

const KEY = 'cc757b36-55b6-4449-8137-78de02af6ff4';
const CONVERSATION_ID = '11111111-1111-4111-8111-111111111111';
const START_ID = '22222222-2222-4222-8222-222222222222';

function processingResponse() {
  return new Response(
    JSON.stringify({
      start_request_id: START_ID,
      conversation_id: CONVERSATION_ID,
      idempotency_status: 'processing',
      retry_after_seconds: 2,
    }),
    {
      status: 202,
      headers: {
        'Content-Type': 'application/json',
        'Retry-After': '3',
      },
    },
  );
}

function createHarness() {
  const fetchImpl = vi.fn<typeof fetch>();
  fetchImpl.mockImplementation(async () => processingResponse());

  const transport = createTransport({
    apiOrigin: 'https://api.example.test',
    // Synthetic test credential, never a real account token.
    getAccessToken: () => 'test-access-token',
    fetchImpl,
  });

  return {
    api: createStartConversationApi(transport),
    fetchImpl,
  };
}

describe('start conversation API', () => {
  it('sends the validated first message with bearer authentication and its key', async () => {
    const { api, fetchImpl } = createHarness();

    const result = await api.start({
      message: '  Hello  ',
      idempotencyKey: KEY,
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);

    const call = fetchImpl.mock.calls[0];
    if (call === undefined) {
      throw new Error('Expected a request.');
    }

    expect(String(call[0])).toBe('https://api.example.test/v1/conversations/start');

    const options = call[1];
    const headers = new Headers(options?.headers);

    expect(options?.method).toBe('POST');
    expect(headers.get('Authorization')).toBe('Bearer test-access-token');
    expect(headers.get('Idempotency-Key')).toBe(KEY);
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(options?.body).toBe(JSON.stringify({ message: 'Hello', channel: 'web' }));

    expect(result).toMatchObject({
      ok: true,
      data: {
        kind: 'processing',
        retryAfterMs: 3_000,
        data: { conversation_id: CONVERSATION_ID },
      },
    });
  });

  it.each(['', '   ', 'a'.repeat(20_001)])(
    'rejects invalid message input without sending it',
    async (message) => {
      const { api, fetchImpl } = createHarness();

      const result = await api.start({
        message,
        idempotencyKey: KEY,
      });

      expect(result.ok).toBe(false);
      expect(fetchImpl).not.toHaveBeenCalled();
    },
  );

  it('rejects an invalid idempotency key without sending a request', async () => {
    const { api, fetchImpl } = createHarness();

    const result = await api.start({
      message: 'Hello',
      idempotencyKey: 'too-short',
    });

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('honors an already-aborted signal', async () => {
    const { api, fetchImpl } = createHarness();
    const controller = new AbortController();
    controller.abort();

    const result = await api.start({ message: 'Hello', idempotencyKey: KEY }, controller.signal);

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('preserves the caller-provided key across explicit recovery calls', async () => {
    const { api, fetchImpl } = createHarness();
    const input = { message: 'Hello', idempotencyKey: KEY };

    await api.start(input);
    await api.start(input);

    expect(fetchImpl).toHaveBeenCalledTimes(2);

    const keys = fetchImpl.mock.calls.map((call) =>
      new Headers(call[1]?.headers).get('Idempotency-Key'),
    );
    const bodies = fetchImpl.mock.calls.map((call) => call[1]?.body);

    expect(keys).toEqual([KEY, KEY]);
    expect(bodies[0]).toBe(bodies[1]);
  });

  it('does not automatically retry an uncertain network failure', async () => {
    const { api, fetchImpl } = createHarness();
    fetchImpl.mockRejectedValueOnce(new TypeError('Synthetic network failure'));

    const result = await api.start({
      message: 'Hello',
      idempotencyKey: KEY,
    });

    expect(result.ok).toBe(false);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('preserves a service-unavailable delay without retrying', async () => {
    const { api, fetchImpl } = createHarness();
    fetchImpl.mockResolvedValueOnce(
      new Response('{}', {
        status: 503,
        headers: {
          'Content-Type': 'application/json',
          'Retry-After': '4',
        },
      }),
    );

    const result = await api.start({
      message: 'Hello',
      idempotencyKey: KEY,
    });

    expect(result).toMatchObject({
      ok: false,
      retryAfterMs: 4_000,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
