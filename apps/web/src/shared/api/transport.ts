// apps/web/src/shared/api/transport.ts

import { parseRetryAfter } from './retry-after';
import { SafeApiError } from './safe-error';

export type TransportResult<T> =
  | {
      readonly ok: true;
      readonly data: T;
      readonly traceId: string | null;
    }
  | {
      readonly ok: false;
      readonly error: SafeApiError;
      readonly retryAfterMs: number | null;
    };

type Authentication = 'none' | 'bearer' | 'cookie' | 'bearer-cookie';

type RequestBody =
  | { readonly kind: 'json'; readonly value: unknown }
  | { readonly kind: 'multipart'; readonly value: FormData };

export interface TransportRequest<T> {
  readonly path: `/v1/${string}`;
  readonly method: 'GET' | 'POST' | 'PATCH';
  readonly authentication: Authentication;
  readonly decode: (value: unknown) => T;
  readonly query?: URLSearchParams;
  readonly body?: RequestBody;
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
}

interface TransportOptions {
  /** Pass apiOrigin from the validated public configuration. */
  readonly apiOrigin: string;
  /** Reads current in-memory state; tokens are not captured at creation. */
  readonly getAccessToken: () => string | null;
  readonly fetchImpl?: typeof fetch;
}

const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_TIMEOUT_MS = 2_147_483_647;
const PATH_PATTERN = /^\/v1\/[a-zA-Z0-9/_-]+$/u;

function failure(error: SafeApiError, retryAfterMs: number | null = null): TransportResult<never> {
  return { ok: false, error, retryAfterMs };
}

function isJsonResponse(response: Response): boolean {
  const mediaType = response.headers.get('Content-Type')?.split(';')[0]?.trim().toLowerCase();

  return mediaType === 'application/json' || /^application\/[\w.+-]+\+json$/u.test(mediaType ?? '');
}

export function createTransport(options: TransportOptions) {
  let origin: URL;

  try {
    origin = new URL(options.apiOrigin);
  } catch {
    throw new Error('Invalid API origin configuration.');
  }

  if (!['http:', 'https:'].includes(origin.protocol) || origin.origin !== options.apiOrigin) {
    throw new Error('Invalid API origin configuration.');
  }

  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);

  return async function request<T>(input: TransportRequest<T>): Promise<TransportResult<T>> {
    const timeoutMs = input.timeoutMs ?? DEFAULT_TIMEOUT_MS;

    if (
      !PATH_PATTERN.test(input.path) ||
      !Number.isInteger(timeoutMs) ||
      timeoutMs <= 0 ||
      timeoutMs > MAX_TIMEOUT_MS ||
      (input.method === 'GET' && input.body !== undefined)
    ) {
      // Programming/configuration failure: no request is sent.
      return failure(SafeApiError.fromLocal('invalid-response'));
    }

    if (input.signal?.aborted) {
      return failure(SafeApiError.fromLocal('aborted'));
    }

    const url = new URL(input.path, origin);
    if (input.query !== undefined) {
      url.search = input.query.toString();
    }

    const controller = new AbortController();
    let abortKind: 'aborted' | 'timeout' | null = null;
    let traceId: string | null = null;

    const abort = (kind: 'aborted' | 'timeout') => {
      if (!controller.signal.aborted) {
        abortKind = kind;
        // Do not propagate a caller-supplied abort reason.
        controller.abort();
      }
    };

    const onAbort = () => abort('aborted');
    input.signal?.addEventListener('abort', onAbort, { once: true });

    const timer = setTimeout(() => abort('timeout'), timeoutMs);

    try {
      const headers = new Headers({ Accept: 'application/json' });
      const usesBearer =
        input.authentication === 'bearer' || input.authentication === 'bearer-cookie';

      if (usesBearer) {
        const token = options.getAccessToken();

        if (!token) {
          return failure(SafeApiError.fromHttp(401, null));
        }

        headers.set('Authorization', `Bearer ${token}`);
      }

      let body: BodyInit | undefined;

      if (input.body?.kind === 'json') {
        try {
          body = JSON.stringify(input.body.value);
        } catch {
          return failure(SafeApiError.fromLocal('invalid-response'));
        }

        if (body === undefined) {
          return failure(SafeApiError.fromLocal('invalid-response'));
        }

        headers.set('Content-Type', 'application/json');
      } else if (input.body?.kind === 'multipart') {
        body = input.body.value;
      }

      const usesCookies =
        input.authentication === 'cookie' || input.authentication === 'bearer-cookie';

      const response = await fetchImpl(url, {
        method: input.method,
        headers,
        ...(body === undefined ? {} : { body }),
        signal: controller.signal,
        credentials: usesCookies ? 'include' : 'omit',
        cache: 'no-store',
        redirect: 'error',
        referrerPolicy: 'no-referrer',
      });

      const headerTraceId = response.headers.get('X-Trace-ID');

      // Reuse the safe error boundary's UUID validation.
      traceId = SafeApiError.fromLocal('invalid-response', headerTraceId).traceId;

      let payload: unknown = null;
      let readableJson = response.status === 204;

      if (isJsonResponse(response) && response.status !== 204) {
        try {
          payload = await response.json();
          readableJson = true;
        } catch {
          // Preserve a known HTTP failure even when its body is malformed.
          readableJson = false;
        }
      } else if (response.body !== null) {
        // Do not read or retain HTML/text error pages.
        await response.body.cancel();
      }

      if (controller.signal.aborted) {
        return failure(SafeApiError.fromLocal(abortKind ?? 'aborted', traceId));
      }

      if (!response.ok) {
        return failure(
          SafeApiError.fromHttp(response.status, payload, headerTraceId),
          parseRetryAfter(response.headers.get('Retry-After')),
        );
      }

      if (!readableJson) {
        return failure(SafeApiError.fromLocal('invalid-response', traceId));
      }

      try {
        // Feature decoders validate enums/shapes and return allowlisted fields.
        const data = input.decode(payload);
        return { ok: true, data, traceId };
      } catch {
        return failure(SafeApiError.fromLocal('invalid-response', traceId));
      }
    } catch {
      // Never preserve fetch exceptions, URLs, credentials, or raw causes.
      return failure(SafeApiError.fromLocal(abortKind ?? 'network', traceId));
    } finally {
      clearTimeout(timer);
      input.signal?.removeEventListener('abort', onAbort);
    }
  };
}
