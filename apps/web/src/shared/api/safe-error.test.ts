// apps/web/src/shared/api/safe-error.test.ts

import { describe, expect, it } from 'vitest';

import { SafeApiError } from './safe-error';

const BODY_TRACE_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';
const HEADER_TRACE_ID = 'bf187e45-c833-444b-bcc5-39465b2be9fc';

describe('SafeApiError.fromHttp', () => {
  it('discards backend messages, validation details, codes, and extra fields', () => {
    const sensitiveText = 'private-customer-content-and-provider-secret';

    const error = SafeApiError.fromHttp(422, {
      error: {
        code: sensitiveText,
        message: sensitiveText,
        trace_id: BODY_TRACE_ID,
        details: [
          {
            location: ['body', sensitiveText],
            message: sensitiveText,
            type: sensitiveText,
          },
        ],
      },
      debug: sensitiveText,
    });

    expect(error).toBeInstanceOf(Error);
    expect(error).toBeInstanceOf(SafeApiError);
    expect(error.message).toBe('Some submitted values could not be accepted. Review your input.');
    expect(error.traceId).toBe(BODY_TRACE_ID);

    expect(JSON.stringify(error)).not.toContain(sensitiveText);
    expect(String(error)).not.toContain(sensitiveText);
    expect(error.stack).not.toContain(sensitiveText);
    expect(error).not.toHaveProperty('cause');
    expect(error).not.toHaveProperty('body');
    expect(error).not.toHaveProperty('details');
    expect(error).not.toHaveProperty('code');
  });

  it('prefers a valid response-header trace ID', () => {
    const error = SafeApiError.fromHttp(
      503,
      { error: { trace_id: BODY_TRACE_ID } },
      HEADER_TRACE_ID.toUpperCase(),
    );

    expect(error.traceId).toBe(HEADER_TRACE_ID);
  });

  it('falls back to a valid envelope trace ID', () => {
    const error = SafeApiError.fromHttp(
      500,
      { error: { trace_id: BODY_TRACE_ID } },
      'invalid-header',
    );

    expect(error.traceId).toBe(BODY_TRACE_ID);
  });

  it.each([
    null,
    undefined,
    '',
    '<html>Upstream failure</html>',
    [],
    {},
    { detail: 'Not Found' },
    { error: null },
    { error: [] },
    { error: { trace_id: 'secret-value' } },
    { error: { trace_id: 123 } },
  ])('handles malformed or noncanonical bodies safely: %j', (body) => {
    const error = SafeApiError.fromHttp(500, body, 'invalid-header');

    expect(error.toJSON()).toEqual({
      kind: 'http',
      message: 'The request could not be completed.',
      status: 500,
      traceId: null,
    });
  });

  it.each([401, 403, 409, 413, 415, 422, 503, 504])(
    'preserves HTTP status %i without deciding retry policy',
    (status) => {
      const error = SafeApiError.fromHttp(status, null);

      expect(error.kind).toBe('http');
      expect(error.status).toBe(status);
      expect(error.message.length).toBeGreaterThan(0);
      expect(error).not.toHaveProperty('retryable');
    },
  );

  it('uses a generic message for an unknown error status', () => {
    const error = SafeApiError.fromHttp(599, {
      error: { message: 'Internal provider exception' },
    });

    expect(error.status).toBe(599);
    expect(error.message).toBe('The request could not be completed.');
  });

  it.each([0, 200, 399, 600, 422.5, Number.NaN, Number.POSITIVE_INFINITY])(
    'treats invalid error status %s as an unexpected response',
    (status) => {
      const error = SafeApiError.fromHttp(status, null, HEADER_TRACE_ID);

      expect(error.toJSON()).toEqual({
        kind: 'invalid-response',
        message: 'The service returned an unexpected response.',
        status: null,
        traceId: HEADER_TRACE_ID,
      });
    },
  );

  it('does not retain the original response object', () => {
    const body = {
      error: {
        trace_id: BODY_TRACE_ID,
        message: 'Original server message',
      },
    };

    const error = SafeApiError.fromHttp(409, body);
    body.error.trace_id = HEADER_TRACE_ID;
    body.error.message = 'Changed server message';

    expect(error.traceId).toBe(BODY_TRACE_ID);
    expect(JSON.stringify(error)).not.toContain('server message');
  });
});

describe('SafeApiError.fromLocal', () => {
  it.each(['network', 'timeout', 'aborted', 'invalid-response'] as const)(
    'represents %s without retaining a raw exception',
    (kind) => {
      const error = SafeApiError.fromLocal(kind);

      expect(error.kind).toBe(kind);
      expect(error.status).toBeNull();
      expect(error.traceId).toBeNull();
      expect(error.message.length).toBeGreaterThan(0);
      expect(error).not.toHaveProperty('cause');
    },
  );

  it('validates correlation information for local failures', () => {
    expect(SafeApiError.fromLocal('timeout', HEADER_TRACE_ID).traceId).toBe(HEADER_TRACE_ID);
    expect(SafeApiError.fromLocal('network', 'sensitive-value').traceId).toBeNull();
  });

  it('serializes only the intended safe fields', () => {
    const error = SafeApiError.fromLocal('aborted');

    expect(JSON.parse(JSON.stringify(error))).toEqual({
      kind: 'aborted',
      message: 'The request was cancelled.',
      status: null,
      traceId: null,
    });
  });
});
