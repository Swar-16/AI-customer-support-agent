// apps/web/src/shared/auth/auth-api.test.ts

import { describe, expect, it, vi } from 'vitest';

import { createTransport } from '../api/transport';
import { createAuthApi } from './auth-api';
import { decodeAuthentication, decodeAuthUser, decodeLogout } from './auth-contract';

function userFixture() {
  return {
    id: 'd44e99cb-8e10-4af8-9bb7-c4d293042943',
    email: 'customer@example.test',
    display_name: null,
    role: 'customer',
    status: 'active',
    created_at: '2026-09-15T10:00:00Z',
  };
}

function authenticationFixture() {
  return {
    user: userFixture(),
    tokens: {
      access_token: 'test-only-access-token',
      token_type: 'Bearer',
      access_token_expires_at: '2026-09-15T10:15:00Z',
      refresh_token_expires_at: '2026-10-15T10:00:00Z',
    },
  };
}

function setup() {
  const fetchImpl = vi.fn<typeof fetch>();
  const api = createAuthApi(
    createTransport({
      apiOrigin: 'https://api.example.test',
      getAccessToken: () => 'test-only-access-token',
      fetchImpl,
    }),
  );

  return { api, fetchImpl };
}

describe('authentication decoders', () => {
  it('projects only confirmed user and token fields', () => {
    const fixture = authenticationFixture();
    const result = decodeAuthentication({
      ...fixture,
      metadata: 'discard-me',
      user: { ...fixture.user, internal_notes: 'discard-me' },
      tokens: { ...fixture.tokens, refresh_token: 'discard-me' },
    });

    expect(result).toEqual(fixture);
    expect(JSON.stringify(result)).not.toContain('discard-me');
  });

  it.each(['owner', 'constructor', '__proto__'])('rejects an unknown role: %s', (role) => {
    expect(() => decodeAuthUser({ ...userFixture(), role })).toThrow(
      'The service returned an unexpected response.',
    );
  });

  it('rejects unknown account statuses', () => {
    expect(() => decodeAuthUser({ ...userFixture(), status: 'pending' })).toThrow();
  });

  it.each(['2026-09-15T10:00:00', '2026-02-30T10:00:00Z', 'not-a-date'])(
    'rejects invalid or timezone-free timestamps: %s',
    (created_at) => {
      expect(() => decodeAuthUser({ ...userFixture(), created_at })).toThrow();
    },
  );

  it('accepts timezone offsets and fractional seconds', () => {
    const created_at = '2026-09-15T15:30:00.123456+05:30';

    expect(decodeAuthUser({ ...userFixture(), created_at }).created_at).toBe(created_at);
  });

  it('rejects missing required nullable fields', () => {
    const fixture = userFixture();
    const { display_name, ...withoutDisplayName } = fixture;

    expect(display_name).toBeNull();
    expect(() => decodeAuthUser(withoutDisplayName)).toThrow();
  });

  it.each([
    { token_type: 'Basic' },
    { access_token: '' },
    { access_token: 'invalid token' },
    { refresh_token_expires_at: '2026-09-15T10:15:00Z' },
  ])('rejects unsupported token responses: %j', (override) => {
    const fixture = authenticationFixture();

    expect(() =>
      decodeAuthentication({
        ...fixture,
        tokens: { ...fixture.tokens, ...override },
      }),
    ).toThrow();
  });

  it('preserves a false logout result instead of inventing success', () => {
    expect(
      decodeLogout({
        logged_out: false,
        session_id: userFixture().id,
        revoked_at: null,
      }).logged_out,
    ).toBe(false);
  });
});

describe('authentication API requests', () => {
  it('projects login credentials without modifying the password', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(authenticationFixture()));

    const input = {
      email: 'customer@example.test',
      password: '  test-password  ',
      role: 'admin',
    };

    const result = await api.login(input);
    expect(result.ok).toBe(true);

    const call = fetchImpl.mock.calls[0];
    expect(String(call?.[0])).toBe('https://api.example.test/v1/auth/login');
    expect(call?.[1]?.credentials).toBe('include');
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      email: input.email,
      password: input.password,
    });
    expect(new Headers(call?.[1]?.headers).has('Authorization')).toBe(false);
  });

  it('does not send an injected registration role', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(authenticationFixture(), { status: 201 }));

    await api.register({
      ...{
        email: 'customer@example.test',
        password: 'test-password',
        role: 'admin',
      },
      display_name: 'Customer',
    });

    const body = JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body));
    expect(body).toEqual({
      email: 'customer@example.test',
      password: 'test-password',
      display_name: 'Customer',
    });
  });

  it('refreshes with cookies and an entirely empty request body', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(authenticationFixture()));

    await api.refresh();

    const call = fetchImpl.mock.calls[0];
    const headers = new Headers(call?.[1]?.headers);

    expect(String(call?.[0])).toBe('https://api.example.test/v1/auth/refresh');
    expect(call?.[1]?.credentials).toBe('include');
    expect(call?.[1]?.body).toBeUndefined();
    expect(headers.has('Content-Type')).toBe(false);
    expect(headers.has('Authorization')).toBe(false);
  });

  it('loads the current user with bearer authentication', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(userFixture()));

    await api.currentUser();

    const call = fetchImpl.mock.calls[0];
    expect(String(call?.[0])).toBe('https://api.example.test/v1/auth/me');
    expect(call?.[1]?.method).toBe('GET');
    expect(call?.[1]?.credentials).toBe('omit');
    expect(new Headers(call?.[1]?.headers).get('Authorization')).toBe(
      'Bearer test-only-access-token',
    );
  });

  it('logs out with both bearer authentication and cookie handling', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(
      Response.json({
        logged_out: true,
        session_id: userFixture().id,
        revoked_at: '2026-09-15T10:05:00Z',
      }),
    );

    const result = await api.logout();

    expect(result.ok).toBe(true);
    const call = fetchImpl.mock.calls[0];
    expect(String(call?.[0])).toBe('https://api.example.test/v1/auth/logout');
    expect(call?.[1]?.credentials).toBe('include');
    expect(call?.[1]?.body).toBeUndefined();
    expect(new Headers(call?.[1]?.headers).has('Authorization')).toBe(true);
  });

  it('converts an unknown response role into a safe transport failure', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json({ ...userFixture(), role: 'unexpected-role' }));

    const result = await api.currentUser();

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected failure');
    expect(result.error.kind).toBe('invalid-response');
  });
});
