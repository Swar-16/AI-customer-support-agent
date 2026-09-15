// apps/web/src/shared/auth/auth-contract.ts

import type { components } from '../api/generated/schema';
import { SafeApiError } from '../api/safe-error';

export type AuthUser = components['schemas']['AuthenticatedUserResponse'];
export type AuthenticationResponse = components['schemas']['BrowserAuthenticationResponse'];
export type LoginInput = components['schemas']['LoginRequest'];
export type RegisterInput = components['schemas']['RegisterRequest'];
export type LogoutResponse = components['schemas']['LogoutResponse'];

const roles = {
  customer: true,
  support_agent: true,
  admin: true,
  system: true,
} satisfies Record<AuthUser['role'], true>;

const statuses = {
  active: true,
  disabled: true,
  deleted: true,
} satisfies Record<AuthUser['status'], true>;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;

const TIMESTAMP_PATTERN =
  /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/u;

function invalid(): never {
  throw SafeApiError.fromLocal('invalid-response');
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return invalid();
  }

  return value as Record<string, unknown>;
}

function string(value: unknown): string {
  if (typeof value !== 'string') return invalid();
  return value;
}

function nullableString(value: unknown): string | null {
  return value === null ? null : string(value);
}

function uuid(value: unknown): string {
  const result = string(value);
  if (!UUID_PATTERN.test(result)) return invalid();
  return result;
}

function timestamp(value: unknown): string {
  const result = string(value);

  if (!TIMESTAMP_PATTERN.test(result) || !Number.isFinite(Date.parse(result))) {
    return invalid();
  }

  // Date.parse can normalize impossible dates such as February 30.
  const datePart = result.slice(0, 10);
  const calendarDate = new Date(`${datePart}T00:00:00Z`);

  if (
    !Number.isFinite(calendarDate.getTime()) ||
    calendarDate.toISOString().slice(0, 10) !== datePart
  ) {
    return invalid();
  }

  return result;
}

function enumValue<T extends string>(value: unknown, allowed: Record<T, true>): T {
  if (typeof value !== 'string' || !Object.prototype.hasOwnProperty.call(allowed, value)) {
    return invalid();
  }

  return value as T;
}

export function decodeAuthUser(value: unknown): AuthUser {
  const input = record(value);

  return {
    id: uuid(input.id),
    email: string(input.email),
    display_name: nullableString(input.display_name),
    role: enumValue(input.role, roles),
    status: enumValue(input.status, statuses),
    created_at: timestamp(input.created_at),
  };
}

/**
 * Contains access credentials for the session controller only.
 * Never put this result in query caches, UI state, logs, or storage.
 */
export function decodeAuthentication(value: unknown): AuthenticationResponse {
  const input = record(value);
  const tokens = record(input.tokens);
  const accessToken = string(tokens.access_token);
  const accessExpiresAt = timestamp(tokens.access_token_expires_at);
  const refreshExpiresAt = timestamp(tokens.refresh_token_expires_at);

  if (
    accessToken.length === 0 ||
    /\s/u.test(accessToken) ||
    tokens.token_type !== 'Bearer' ||
    Date.parse(refreshExpiresAt) <= Date.parse(accessExpiresAt)
  ) {
    return invalid();
  }

  return {
    user: decodeAuthUser(input.user),
    tokens: {
      access_token: accessToken,
      token_type: 'Bearer',
      access_token_expires_at: accessExpiresAt,
      refresh_token_expires_at: refreshExpiresAt,
    },
  };
}

export function decodeLogout(value: unknown): LogoutResponse {
  const input = record(value);

  if (typeof input.logged_out !== 'boolean') return invalid();

  return {
    logged_out: input.logged_out,
    session_id: uuid(input.session_id),
    revoked_at: input.revoked_at === null ? null : timestamp(input.revoked_at),
  };
}
