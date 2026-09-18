// apps/web/src/shared/api/transport.test.ts

import { afterEach, describe, expect, it, vi } from 'vitest';

import { createTransport } from './transport';

const TRACE_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';

function decodeFixture(value: unknown): { value: string } {
  if (
    typeof value !== 'object' ||
    value === null ||
    !('value' in value) ||
    typeof value.value !== 'string'
  ) {
    throw new Error('Invalid fixture');
  }

  return { value: value.value };
}

function setup() {
  const fetchImpl = vi.fn<typeof fetch>();
  const getAccessToken = vi.fn((): string | null => 'test-access-token');
  const request = createTransport({
    apiOrigin: 'https://api.example.test',
    getAccessToken,
    fetchImpl,
  });

  return { request, fetchImpl, getAccessToken };
}

const getRequest = {
  path: '/v1/conversations',
  method: 'GET',
  authentication: 'bearer',
  decode: decodeFixture,
} as const;

afterEach(() => {
  vi.useRealTimers();
});

describe('transport', () => {
  it('decodes success and discards fields excluded by the decoder', async () => {
    const { request, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(
      Response.json(
        { value: 'accepted', private_metadata: 'discard-me' },
        { headers: { 'X-Trace-ID': TRACE_ID } },
      ),
    );

    const result = await request(getRequest);

    expect(result).toEqual({
      ok: true,
      data: { value: 'accepted' },
      traceId: TRACE_ID,
    });
    expect(JSON.stringify(result)).not.toContain('discard-me');

    const init = fetchImpl.mock.calls[0]?.[1];
    expect(init?.credentials).toBe('omit');
    expect(init?.cache).toBe('no-store');
    expect(init?.redirect).toBe('error');
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer test-access-token');
  });

  it('returns sanitized HTTP errors and preserves Retry-After without retrying', async () => {
    const { request, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(
      Response.json(
        { error: { message: 'provider-secret', trace_id: TRACE_ID } },
        { status: 503, headers: { 'Retry-After': '5' } },
      ),
    );

    const result = await request(getRequest);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected failure');

    expect(result.error.status).toBe(503);
    expect(result.error.traceId).toBe(TRACE_ID);
    expect(result.retryAfterMs).toBe(5_000);
    expect(JSON.stringify(result)).not.toContain('provider-secret');
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('preserves HTTP status when an error body is malformed JSON', async () => {
    const { request, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(
      new Response('{broken', {
        status: 409,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await request(getRequest);
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected failure');

    expect(result.error.status).toBe(409);
  });

  it('rejects an unexpected successful response shape', async () => {
    const { request, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json({ unexpected: 'secret' }));

    const result = await request(getRequest);
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected failure');

    expect(result.error.kind).toBe('invalid-response');
    expect(JSON.stringify(result)).not.toContain('secret');
  });

  it('sends JSON with explicit cookie credentials', async () => {
    const { request, fetchImpl, getAccessToken } = setup();
    fetchImpl.mockResolvedValue(Response.json({ value: 'accepted' }));

    await request({
      ...getRequest,
      path: '/v1/auth/login',
      method: 'POST',
      authentication: 'cookie',
      body: { kind: 'json', value: { fixture: true } },
    });

    const init = fetchImpl.mock.calls[0]?.[1];
    expect(init?.credentials).toBe('include');
    expect(init?.body).toBe('{"fixture":true}');
    expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json');
    expect(new Headers(init?.headers).has('Authorization')).toBe(false);
    expect(getAccessToken).not.toHaveBeenCalled();
  });

  it('leaves multipart Content-Type to the browser', async () => {
    const { request, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json({ value: 'accepted' }));
    const form = new FormData();
    form.append('file', new Blob(['fixture']), 'fixture.txt');

    await request({
      ...getRequest,
      method: 'POST',
      body: { kind: 'multipart', value: form },
    });

    const init = fetchImpl.mock.calls[0]?.[1];
    expect(init?.body).toBe(form);
    expect(new Headers(init?.headers).has('Content-Type')).toBe(false);
  });

  it('does not send a bearer request without an access token', async () => {
    const { request, fetchImpl, getAccessToken } = setup();
    getAccessToken.mockReturnValue(null);

    const result = await request(getRequest);
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected failure');

    expect(result.error.status).toBe(401);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('does not send an already-cancelled request', async () => {
    const { request, fetchImpl } = setup();
    const controller = new AbortController();
    controller.abort('sensitive-reason');

    const result = await request({ ...getRequest, signal: controller.signal });
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected failure');

    expect(result.error.kind).toBe('aborted');
    expect(JSON.stringify(result)).not.toContain('sensitive-reason');
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('aborts an in-flight request when its timeout expires', async () => {
    vi.useFakeTimers();
    const { request, fetchImpl } = setup();

    fetchImpl.mockImplementation(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new Error('raw-fetch-error')), {
            once: true,
          });
        }),
    );

    const pending = request({ ...getRequest, timeoutMs: 100 });
    await vi.advanceTimersByTimeAsync(100);
    const result = await pending;

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected failure');

    expect(result.error.kind).toBe('timeout');
    expect(JSON.stringify(result)).not.toContain('raw-fetch-error');
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('sanitizes network exceptions', async () => {
    const { request, fetchImpl } = setup();
    fetchImpl.mockRejectedValue(new Error('secret-token-and-request-content'));

    const result = await request(getRequest);
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected failure');

    expect(result.error.kind).toBe('network');
    expect(JSON.stringify(result)).not.toContain('secret-token');
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('rejects traversal paths before sending credentials', async () => {
    const { request, fetchImpl } = setup();

    const result = await request({
      ...getRequest,
      path: '/v1/../../other',
    });

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
