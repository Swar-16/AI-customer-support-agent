// apps/web/src/features/auth/logout-page.test.tsx

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it, vi } from 'vitest';

import { ApplicationProviders } from '../../app/providers';
import { createApplicationRuntime } from '../../app/runtime';
import { createSessionCoordinator } from '../../shared/auth/session-coordinator';
import { LogoutPage } from './logout-page';

const SESSION_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';

function authenticationFixture() {
  return {
    user: {
      id: SESSION_ID,
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

function confirmedLogout() {
  return Response.json({
    logged_out: true,
    session_id: SESSION_ID,
    revoked_at: '2026-09-15T10:05:00Z',
  });
}

async function setup() {
  const fetchImpl = vi.fn<typeof fetch>();
  fetchImpl.mockResolvedValueOnce(Response.json(authenticationFixture()));

  const runtime = createApplicationRuntime({
    apiOrigin: 'https://api.example.test',
    fetchImpl,

    createCoordinator(onRemoteInvalidation) {
      return createSessionCoordinator(
        {
          exclusive: async <T,>(task: () => Promise<T>): Promise<T> => await task(),
          notify: () => undefined,
          listen: () => () => undefined,
          close: () => undefined,
        },
        onRemoteInvalidation,
      );
    },
  });

  await runtime.session.login({
    email: 'customer@example.test',
    password: 'test-only-password',
  });

  // Count only requests made after setup login.
  fetchImpl.mockClear();

  const view = render(
    <ApplicationProviders runtime={runtime}>
      <MemoryRouter initialEntries={['/logout']}>
        <Routes>
          <Route path="/logout" element={<LogoutPage />} />
          <Route path="/login" element={<h1>Login destination</h1>} />
        </Routes>
      </MemoryRouter>
    </ApplicationProviders>,
  );

  return {
    runtime,
    fetchImpl,
    cleanup() {
      view.unmount();
      runtime.dispose();
    },
  };
}

describe('logout page', () => {
  it('requires explicit confirmation before making a request', async () => {
    const { fetchImpl, cleanup } = await setup();

    expect(screen.getByRole('button', { name: 'Confirm sign out' })).toBeEnabled();
    expect(fetchImpl).not.toHaveBeenCalled();

    cleanup();
  });

  it('reports success only after confirmation and clears private queries', async () => {
    const { runtime, fetchImpl, cleanup } = await setup();
    fetchImpl.mockResolvedValueOnce(confirmedLogout());

    runtime.queryClient.setQueryData(['private-test-record'], {
      value: 'private-fixture',
    });

    fireEvent.click(screen.getByRole('button', { name: 'Confirm sign out' }));

    expect(await screen.findByRole('heading', { name: 'You are signed out' })).toBeInTheDocument();

    expect(runtime.session.getSnapshot().phase).toBe('anonymous');
    expect(runtime.queryClient.getQueryCache().getAll()).toHaveLength(0);
    expect(screen.getByRole('link', { name: 'Return to sign-in' })).toHaveAttribute(
      'href',
      '/login',
    );

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(String(fetchImpl.mock.calls[0]?.[0])).toBe('https://api.example.test/v1/auth/logout');

    cleanup();
  });

  it('keeps the screen mounted while pending and prevents double submission', async () => {
    const { fetchImpl, cleanup } = await setup();
    let finish!: (response: Response) => void;

    fetchImpl.mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
    );

    const button = screen.getByRole('button', { name: 'Confirm sign out' });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByRole('button', { name: 'Signing out…' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Waiting for sign-out confirmation…');

    await act(async () => {
      finish(confirmedLogout());
    });

    expect(screen.getByRole('heading', { name: 'You are signed out' })).toBeInTheDocument();
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    cleanup();
  });

  it('does not claim success or retry after a network failure', async () => {
    const { fetchImpl, cleanup } = await setup();
    fetchImpl.mockRejectedValueOnce(new Error('private-provider-details'));

    fireEvent.click(screen.getByRole('button', { name: 'Confirm sign out' }));

    expect(
      await screen.findByRole('heading', {
        name: 'Sign-out could not be confirmed',
      }),
    ).toBeInTheDocument();

    expect(screen.getByRole('alert')).toHaveTextContent(
      'We could not confirm that the server session',
    );
    expect(screen.queryByText('private-provider-details')).toBeNull();
    expect(screen.queryByRole('heading', { name: 'You are signed out' })).toBeNull();
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    cleanup();
  });

  it('does not treat logged_out false as success', async () => {
    const { fetchImpl, cleanup } = await setup();

    fetchImpl.mockResolvedValueOnce(
      Response.json({
        logged_out: false,
        session_id: SESSION_ID,
        revoked_at: null,
      }),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Confirm sign out' }));

    expect(
      await screen.findByRole('heading', {
        name: 'Sign-out could not be confirmed',
      }),
    ).toBeInTheDocument();

    cleanup();
  });

  it('does not interpret a 401 as confirmed cookie deletion', async () => {
    const { fetchImpl, cleanup } = await setup();
    fetchImpl.mockResolvedValueOnce(Response.json({}, { status: 401 }));

    fireEvent.click(screen.getByRole('button', { name: 'Confirm sign out' }));

    expect(
      await screen.findByRole('heading', {
        name: 'Sign-out could not be confirmed',
      }),
    ).toBeInTheDocument();

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    cleanup();
  });

  it('redirects 2.5 seconds after confirmed sign-out', async () => {
    const { fetchImpl, cleanup } = await setup();
    fetchImpl.mockResolvedValueOnce(confirmedLogout());

    vi.useFakeTimers();

    try {
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Confirm sign out' }));
      });

      expect(screen.getByRole('heading', { name: 'You are signed out' })).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1499);
      });

      expect(screen.queryByRole('heading', { name: 'Login destination' })).not.toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });

      expect(screen.getByRole('heading', { name: 'Login destination' })).toBeInTheDocument();

      expect(fetchImpl).toHaveBeenCalledTimes(1);
    } finally {
      cleanup();
      vi.useRealTimers();
    }
  });

  it('does not redirect after unconfirmed sign-out', async () => {
    const { fetchImpl, cleanup } = await setup();
    fetchImpl.mockRejectedValueOnce(new Error('Synthetic network failure'));

    vi.useFakeTimers();

    try {
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Confirm sign out' }));
      });

      expect(
        screen.getByRole('heading', {
          name: 'Sign-out could not be confirmed',
        }),
      ).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });

      expect(screen.queryByRole('heading', { name: 'Login destination' })).not.toBeInTheDocument();

      expect(
        screen.getByRole('heading', {
          name: 'Sign-out could not be confirmed',
        }),
      ).toBeInTheDocument();
    } finally {
      cleanup();
      vi.useRealTimers();
    }
  });
});
