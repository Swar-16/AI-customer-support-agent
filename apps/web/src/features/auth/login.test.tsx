// apps/web/src/features/auth/login.test.tsx

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuthUser } from '../../shared/auth/auth-contract';
import { SafeApiError } from '../../shared/api/safe-error';
import type { SessionOutcome } from '../../shared/auth/session-controller';
import { LoginPage } from './login-page';
import { loginDestination } from './login-destination';
import { loginSchema } from './login-schema';

const { login } = vi.hoisted(() => ({
  login: vi.fn<(input: { email: string; password: string }) => Promise<SessionOutcome>>(),
}));

vi.mock('../../shared/auth/session-context', () => ({
  useSession: () => ({
    phase: 'anonymous',
    user: null,
    error: null,
  }),
  useSessionController: () => ({ login }),
}));

function user(role: AuthUser['role']): AuthUser {
  return {
    id: 'd44e99cb-8e10-4af8-9bb7-c4d293042943',
    email: 'person@example.test',
    display_name: null,
    role,
    status: 'active',
    created_at: '2026-09-15T10:00:00Z',
  };
}

function fillCredentials() {
  fireEvent.change(screen.getByLabelText('Email address'), {
    target: { value: ' CUSTOMER@example.test ' },
  });
  fireEvent.change(screen.getByLabelText('Password'), {
    target: { value: '  password-with-spaces  ' },
  });
}

beforeEach(() => {
  login.mockReset();

  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(() => true),
    })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('login validation', () => {
  it('normalizes email while preserving the password', () => {
    expect(
      loginSchema.parse({
        email: ' CUSTOMER@example.test ',
        password: '  password  ',
      }),
    ).toEqual({
      email: 'customer@example.test',
      password: '  password  ',
    });
  });

  it('enforces the UTF-8 byte limit', () => {
    expect(
      loginSchema.safeParse({
        email: 'customer@example.test',
        password: 'é'.repeat(512),
      }).success,
    ).toBe(true);

    expect(
      loginSchema.safeParse({
        email: 'customer@example.test',
        password: 'é'.repeat(513),
      }).success,
    ).toBe(false);
  });
});

describe('login destination', () => {
  it('preserves an authorized workspace destination', () => {
    expect(loginDestination({ returnTo: '/knowledge' }, user('admin'))).toBe('/knowledge');
  });

  it.each([
    'https://example.test',
    '//example.test',
    '/login',
    '/knowledge',
    '/chat?token=unexpected',
    '/chat/../operations',
  ])('rejects an unauthorized or unsupported return path: %s', (returnTo) => {
    expect(loginDestination({ returnTo }, user('customer'))).toBe('/chat');
  });

  it('does not grant disabled accounts a destination', () => {
    expect(
      loginDestination({ returnTo: '/operations' }, { ...user('admin'), status: 'disabled' }),
    ).toBeNull();
  });
});

describe('login form', () => {
  it('validates empty input without sending a request', async () => {
    render(<LoginPage />);

    fireEvent.submit(screen.getByRole('form', { name: 'Sign in' }));

    expect(await screen.findByText('Enter your password.')).toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
  });

  it('shows a safe credential error and clears the password', async () => {
    login.mockResolvedValue({
      ok: false,
      reason: 'request-failed',
      error: SafeApiError.fromHttp(401, null),
      retryAfterMs: null,
    });

    render(<LoginPage />);
    fillCredentials();
    fireEvent.submit(screen.getByRole('form', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Sign-in failed. Check your email and password.',
    );

    expect(login).toHaveBeenCalledWith({
      email: 'customer@example.test',
      password: '  password-with-spaces  ',
    });

    await waitFor(() => {
      expect(screen.getByLabelText('Password')).toHaveValue('');
    });
  });

  it('prevents duplicate submissions while a request is pending', async () => {
    let finish!: (outcome: SessionOutcome) => void;

    login.mockReturnValue(
      new Promise<SessionOutcome>((resolve) => {
        finish = resolve;
      }),
    );

    render(<LoginPage />);
    fillCredentials();

    const form = screen.getByRole('form', { name: 'Sign in' });
    fireEvent.submit(form);

    await waitFor(() => {
      expect(login).toHaveBeenCalledTimes(1);
    });

    fireEvent.submit(form);
    expect(screen.getByRole('button', { name: 'Signing in…' })).toBeDisabled();

    await act(async () => {
      finish({ ok: true });
    });

    expect(login).toHaveBeenCalledTimes(1);
  });
});
