// apps/web/src/shared/api/transport-start.test.ts
import { describe, expect, it, vi } from 'vitest';

import { createTransport, type TransportRequest, type TransportResponseContext } from './transport';

const IDEMPOTENCY_KEY = '36a737a9-4069-45ba-8372-893532491608';
const TRACE_ID = 'c5ff757d-ecc2-41b1-9003-e5f7ca758628';

function createHarness(response: Response) {
  const fetchImpl = vi.fn<typeof fetch>();
  fetchImpl.mockResolvedValue(response);

  const request = createTransport({
    apiOrigin: 'https://api.example.test',
    getAccessToken: () => null,
    fetchImpl,
  });

  return { request, fetchImpl };
}

function startRequest(
  overrides: Partial<TransportRequest<TransportResponseContext>> = {},
): TransportRequest<TransportResponseContext> {
  return {
    path: '/v1/conversations/start',
    method: 'POST',
    // These tests isolate transport behavior from authentication.
    authentication: 'none',
    idempotencyKey: IDEMPOTENCY_KEY,
    body: {
      kind: 'json',
      value: { message: 'Hello', channel: 'web' },
    },
    decode: (_value, context) => context,
    ...overrides,
  };
}

describe('conversation-start transport support', () => {
  it.each([200, 201, 202])('passes HTTP %i and approved headers to the decoder', async (status) => {
    const { request, fetchImpl } = createHarness(
      new Response('{}', {
        status,
        headers: {
          'Content-Type': 'application/json',
          'X-Trace-ID': TRACE_ID,
          'Retry-After': '2',
        },
      }),
    );

    const result = await request(startRequest());

    expect(result).toEqual({
      ok: true,
      data: {
        status,
        traceId: TRACE_ID,
        retryAfterMs: 2_000,
      },
      traceId: TRACE_ID,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    const call = fetchImpl.mock.calls[0];
    expect(call).toBeDefined();

    const headers = new Headers(call?.[1]?.headers);
    expect(headers.get('Idempotency-Key')).toBe(IDEMPOTENCY_KEY);
  });

  it.each([
    '',
    'short',
    'a'.repeat(256),
    'contains a space here',
    'abcdefghijklmnop\n',
    'abcdefghijklmnopé',
  ])('rejects an invalid key before sending a request', async (key) => {
    const { request, fetchImpl } = createHarness(
      new Response('{}', {
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await request(startRequest({ idempotencyKey: key }));

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('does not attach the key to ordinary message submissions', async () => {
    const { request, fetchImpl } = createHarness(
      new Response('{}', {
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await request(
      startRequest({
        path: '/v1/conversations/example/messages',
      }),
    );

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('keeps existing single-argument decoders working', async () => {
    const { request } = createHarness(
      new Response('{"value":"ready"}', {
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await request({
      path: '/v1/health',
      method: 'GET',
      authentication: 'none',
      decode: (value: unknown) => value,
    });

    expect(result).toEqual({
      ok: true,
      data: { value: 'ready' },
      traceId: null,
    });
  });

  it('preserves Retry-After on failure without retrying the mutation', async () => {
    const { request, fetchImpl } = createHarness(
      new Response('{}', {
        status: 503,
        headers: {
          'Content-Type': 'application/json',
          'Retry-After': '3',
        },
      }),
    );

    const result = await request(startRequest());

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error('Expected an unsuccessful transport result.');
    }

    expect(result.retryAfterMs).toBe(3_000);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
