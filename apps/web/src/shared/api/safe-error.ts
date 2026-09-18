// apps/web/src/shared/api/safe-error.ts

export type ApiFailureKind = 'http' | 'network' | 'timeout' | 'aborted' | 'invalid-response';

interface SafeFailure {
  readonly kind: ApiFailureKind;
  readonly message: string;
  readonly status: number | null;
  readonly traceId: string | null;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;

function readTraceId(value: unknown): string | null {
  if (typeof value !== 'string' || !UUID_PATTERN.test(value)) {
    return null;
  }

  return value.toLowerCase();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readBodyTraceId(body: unknown): string | null {
  if (!isRecord(body) || !isRecord(body.error)) {
    return null;
  }

  return readTraceId(body.error.trace_id);
}

function httpMessage(status: number): string {
  switch (status) {
    case 400:
      return 'The request could not be accepted.';
    case 401:
      return 'Authentication is required or could not be verified.';
    case 403:
      return 'This request is not permitted.';
    case 404:
      return 'The requested item could not be found.';
    case 409:
      return 'The request conflicts with the current state. Refresh before trying again.';
    case 413:
      return 'The submitted content is too large.';
    case 415:
      return 'This content type is not supported.';
    case 422:
      return 'Some submitted values could not be accepted. Review your input.';
    case 503:
      return 'The service is temporarily unavailable.';
    case 504:
      return 'The service did not respond in time. Check the current state before trying again.';
    default:
      return 'The request could not be completed.';
  }
}

function localMessage(kind: Exclude<ApiFailureKind, 'http'>): string {
  switch (kind) {
    case 'network':
      return 'The service could not be reached. Check your connection.';
    case 'timeout':
      return 'The request timed out. Check the current state before trying again.';
    case 'aborted':
      return 'The request was cancelled.';
    case 'invalid-response':
      return 'The service returned an unexpected response.';
  }
}

/**
 * Contains only frontend-owned text and validated correlation information.
 * Never attach response bodies, request data, or raw exception causes.
 */
export class SafeApiError extends Error implements SafeFailure {
  readonly kind: ApiFailureKind;
  readonly status: number | null;
  readonly traceId: string | null;

  private constructor(failure: SafeFailure) {
    super(failure.message);

    this.name = 'SafeApiError';
    this.kind = failure.kind;
    this.status = failure.status;
    this.traceId = failure.traceId;
  }

  static fromHttp(
    status: number,
    body: unknown,
    headerTraceId: string | null = null,
  ): SafeApiError {
    const traceId = readTraceId(headerTraceId) ?? readBodyTraceId(body);

    if (!Number.isInteger(status) || status < 400 || status > 599) {
      return SafeApiError.fromLocal('invalid-response', traceId);
    }

    return new SafeApiError({
      kind: 'http',
      message: httpMessage(status),
      status,
      traceId,
    });
  }

  static fromLocal(
    kind: Exclude<ApiFailureKind, 'http'>,
    headerTraceId: string | null = null,
  ): SafeApiError {
    return new SafeApiError({
      kind,
      message: localMessage(kind),
      status: null,
      traceId: readTraceId(headerTraceId),
    });
  }

  toJSON(): SafeFailure {
    return {
      kind: this.kind,
      message: this.message,
      status: this.status,
      traceId: this.traceId,
    };
  }
}
