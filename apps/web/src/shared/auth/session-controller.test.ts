// apps/web/src/shared/auth/session-controller.test.ts

import { describe, expect, it, vi } from 'vitest';

import { SafeApiError } from '../api/safe-error';
import type { TransportResult } from '../api/transport';
import type { createAuthApi } from './auth-api';
import type { AuthenticationResponse } from './auth-contract';
import { createSessionController } from './session-controller';
import { createSessionCoordinator } from './session-coordinator';
import type { SessionCoordinationDependencies } from './session-coordinator';

type AuthApi = ReturnType<typeof createAuthApi>;

function authentication(): AuthenticationResponse {
  return {
    user: {
      id: 'd44e99cb-8e10-4af8-9bb7-c4d293042943',
      email: 'customer@example.test',
      display_name: 'Customer',
      role: 'customer',
      status: 'active',
      created_at: '2026-09-15T10:00:00Z',
    },
    tokens: {
      access_token: 'test-only-private-token',
      token_type: 'Bearer',
      access_token_expires_at: '2026-09-15T10:15:00Z',
      refresh_token_expires_at: '2026-10-15T10:00:00Z',
    },
  };
}

function success<T>(data: T): TransportResult<T> {
  return { ok: true, data, traceId: null };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });

  return { promise, resolve };
}

function setup(
  exclusive: SessionCoordinationDependencies['exclusive'] = async <T>(
    task: () => Promise<T>,
  ): Promise<T> => await task(),
) {
  const api = {
    login: vi.fn<AuthApi['login']>(),
    register: vi.fn<AuthApi['register']>(),
    refresh: vi.fn<AuthApi['refresh']>(),
    currentUser: vi.fn<AuthApi['currentUser']>(),
    logout: vi.fn<AuthApi['logout']>(),
  };

  const clearPrivateState = vi.fn();
  const notify = vi.fn<SessionCoordinationDependencies['notify']>();
  const close = vi.fn();
  const stopListening = vi.fn();

  let readToken: () => string | null = () => null;
  let receive: (value: unknown) => void = () => undefined;

  const controller = createSessionController({
    createApi(getAccessToken) {
      readToken = getAccessToken;
      return api;
    },

    createCoordinator(onRemoteInvalidation) {
      return createSessionCoordinator(
        {
          exclusive,
          notify,
          listen(listener) {
            receive = listener;
            return stopListening;
          },
          close,
        },
        onRemoteInvalidation,
      );
    },

    clearPrivateState,
  });

  return {
    controller,
    api,
    clearPrivateState,
    notify,
    close,
    stopListening,
    readToken: () => readToken(),
    invalidateRemotely: () => receive({ version: 1, type: 'session-invalidated' }),
  };
}

const credentials = {
  email: 'customer@example.test',
  password: 'test-only-password',
};

describe('session controller', () => {
  it('keeps credentials out of public snapshots and method results', async () => {
    const { controller, api, readToken } = setup();
    api.login.mockResolvedValue(success(authentication()));

    const result = await controller.login(credentials);

    expect(result).toEqual({ ok: true });
    expect(controller.getSnapshot().phase).toBe('authenticated');
    expect(readToken()).toBe('test-only-private-token');

    const publicState = JSON.stringify({
      snapshot: controller.getSnapshot(),
      expiry: controller.getExpiry(),
      result,
    });

    expect(publicState).not.toContain('test-only-private-token');
    expect(publicState).not.toContain('test-only-password');
    expect(Object.isFrozen(controller.getSnapshot())).toBe(true);
    expect(Object.isFrozen(controller.getSnapshot().user)).toBe(true);
  });

  it('shares concurrent refresh calls', async () => {
    const { controller, api } = setup();
    const pending = deferred<TransportResult<AuthenticationResponse>>();
    api.refresh.mockReturnValue(pending.promise);

    const first = controller.refresh();
    const second = controller.refresh();

    expect(first).toBe(second);
    await vi.waitFor(() => {
      expect(api.refresh).toHaveBeenCalledTimes(1);
    });

    pending.resolve(success(authentication()));
    await expect(first).resolves.toEqual({ ok: true });
    expect(controller.getSnapshot().phase).toBe('authenticated');
  });

  it('prevents logout from overlapping a refresh', async () => {
    const { controller, api } = setup();
    const pending = deferred<TransportResult<AuthenticationResponse>>();
    api.refresh.mockReturnValue(pending.promise);

    const refreshing = controller.refresh();
    await expect(controller.logout()).resolves.toEqual({
      ok: false,
      reason: 'busy',
    });
    expect(api.logout).not.toHaveBeenCalled();

    pending.resolve(success(authentication()));
    await refreshing;
  });

  it('does not repeat an uncertain refresh', async () => {
    const { controller, api, readToken } = setup();
    api.refresh.mockResolvedValue({
      ok: false,
      error: SafeApiError.fromLocal('timeout'),
      retryAfterMs: null,
    });

    const result = await controller.refresh();

    expect(result.ok).toBe(false);
    expect(controller.getSnapshot().phase).toBe('unavailable');
    expect(readToken()).toBeNull();

    await expect(controller.refresh()).resolves.toEqual({
      ok: false,
      reason: 'reauthentication-required',
    });
    expect(api.refresh).toHaveBeenCalledTimes(1);
  });

  it('clears credentials after confirmed logout', async () => {
    const { controller, api, readToken, clearPrivateState } = setup();
    api.login.mockResolvedValue(success(authentication()));
    api.logout.mockResolvedValue(
      success({
        logged_out: true,
        session_id: authentication().user.id,
        revoked_at: '2026-09-15T10:05:00Z',
      }),
    );

    await controller.login(credentials);
    await expect(controller.logout()).resolves.toEqual({ ok: true });

    expect(readToken()).toBeNull();
    expect(controller.getSnapshot()).toEqual({
      phase: 'anonymous',
      user: null,
      error: null,
    });
    expect(controller.getExpiry()).toEqual({
      accessExpiresAt: null,
      refreshExpiresAt: null,
    });
    expect(clearPrivateState).toHaveBeenCalled();
  });

  it('does not claim logout succeeded after a network failure', async () => {
    const { controller, api } = setup();
    api.login.mockResolvedValue(success(authentication()));
    api.logout.mockResolvedValue({
      ok: false,
      error: SafeApiError.fromLocal('network'),
      retryAfterMs: null,
    });

    await controller.login(credentials);
    const result = await controller.logout();

    expect(result.ok).toBe(false);
    expect(controller.getSnapshot().phase).toBe('unavailable');
    expect(controller.getSnapshot().user).toBeNull();
    expect(api.logout).toHaveBeenCalledTimes(1);
  });

  it('does not claim logout succeeded when the response says false', async () => {
    const { controller, api } = setup();
    api.login.mockResolvedValue(success(authentication()));
    api.logout.mockResolvedValue(
      success({
        logged_out: false,
        session_id: authentication().user.id,
        revoked_at: null,
      }),
    );

    await controller.login(credentials);

    await expect(controller.logout()).resolves.toEqual({
      ok: false,
      reason: 'logout-unconfirmed',
    });
    expect(controller.getSnapshot().phase).toBe('unavailable');
  });

  it('denies interactive access to system accounts', async () => {
    const { controller, api } = setup();
    const response = authentication();
    response.user.role = 'system';
    api.login.mockResolvedValue(success(response));

    await expect(controller.login(credentials)).resolves.toEqual({
      ok: false,
      reason: 'unsupported-account',
    });
    expect(controller.getSnapshot().phase).toBe('unavailable');
    expect(controller.getSnapshot().user).toBeNull();
  });

  it('removes subscribers when they unsubscribe', async () => {
    const { controller, api } = setup();
    api.login.mockResolvedValue(success(authentication()));
    const listener = vi.fn();
    const unsubscribe = controller.subscribe(listener);

    unsubscribe();
    await controller.login(credentials);

    expect(listener).not.toHaveBeenCalled();
  });
});

describe('coordinated session invalidation', () => {
  it('discards a successful refresh response after remote invalidation', async () => {
    const { controller, api, readToken, invalidateRemotely } = setup();
    const pending = deferred<TransportResult<AuthenticationResponse>>();
    api.refresh.mockReturnValue(pending.promise);

    const operation = controller.refresh();

    await vi.waitFor(() => {
      expect(api.refresh).toHaveBeenCalledTimes(1);
    });

    invalidateRemotely();
    pending.resolve(success(authentication()));

    await expect(operation).resolves.toEqual({
      ok: false,
      reason: 'session-changed',
    });

    expect(readToken()).toBeNull();
    expect(controller.getSnapshot()).toEqual({
      phase: 'unavailable',
      user: null,
      error: null,
    });
  });

  it('does not let a stale failure overwrite invalidated state', async () => {
    const { controller, api, invalidateRemotely } = setup();
    const pending = deferred<TransportResult<AuthenticationResponse>>();
    api.refresh.mockReturnValue(pending.promise);

    const operation = controller.refresh();

    await vi.waitFor(() => {
      expect(api.refresh).toHaveBeenCalledTimes(1);
    });

    invalidateRemotely();
    const invalidatedSnapshot = controller.getSnapshot();

    pending.resolve({
      ok: false,
      error: SafeApiError.fromHttp(401, null),
      retryAfterMs: null,
    });

    await expect(operation).resolves.toEqual({
      ok: false,
      reason: 'session-changed',
    });

    expect(controller.getSnapshot()).toBe(invalidatedSnapshot);
  });

  it('rejects invalidated queued work without sending or broadcasting', async () => {
    const gate = deferred<void>();

    const exclusive: SessionCoordinationDependencies['exclusive'] = async <T>(
      task: () => Promise<T>,
    ): Promise<T> => {
      await gate.promise;
      return await task();
    };

    const { controller, api, notify, invalidateRemotely } = setup(exclusive);
    const operation = controller.refresh();

    invalidateRemotely();
    gate.resolve();

    await expect(operation).resolves.toEqual({
      ok: false,
      reason: 'session-changed',
    });

    expect(api.refresh).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
  });

  it('does not broadcast for a refresh blocked after an uncertain failure', async () => {
    const { controller, api, notify } = setup();

    api.refresh.mockResolvedValue({
      ok: false,
      error: SafeApiError.fromLocal('timeout'),
      retryAfterMs: null,
    });

    await controller.refresh();
    expect(notify).toHaveBeenCalledTimes(1);
    notify.mockClear();

    await expect(controller.refresh()).resolves.toEqual({
      ok: false,
      reason: 'reauthentication-required',
    });

    expect(notify).not.toHaveBeenCalled();
    expect(api.refresh).toHaveBeenCalledTimes(1);
  });

  it('clears an authenticated session without starting another refresh', async () => {
    const { controller, api, readToken, clearPrivateState, invalidateRemotely } = setup();

    api.login.mockResolvedValue(success(authentication()));
    await controller.login(credentials);
    clearPrivateState.mockClear();

    invalidateRemotely();

    expect(readToken()).toBeNull();
    expect(controller.getSnapshot().user).toBeNull();
    expect(controller.getSnapshot().phase).toBe('unavailable');
    expect(clearPrivateState).toHaveBeenCalledTimes(1);
    expect(api.refresh).not.toHaveBeenCalled();
  });

  it('discards an in-flight login result after disposal', async () => {
    const { controller, api, readToken, close, stopListening } = setup();
    const pending = deferred<TransportResult<AuthenticationResponse>>();
    api.login.mockReturnValue(pending.promise);

    const operation = controller.login(credentials);

    await vi.waitFor(() => {
      expect(api.login).toHaveBeenCalledTimes(1);
    });

    controller.dispose();
    controller.dispose();
    pending.resolve(success(authentication()));

    await expect(operation).resolves.toEqual({
      ok: false,
      reason: 'session-changed',
    });

    expect(readToken()).toBeNull();
    expect(close).toHaveBeenCalledTimes(1);
    expect(stopListening).toHaveBeenCalledTimes(1);

    await expect(controller.refresh()).resolves.toEqual({
      ok: false,
      reason: 'session-changed',
    });

    expect(api.refresh).not.toHaveBeenCalled();
  });
});
