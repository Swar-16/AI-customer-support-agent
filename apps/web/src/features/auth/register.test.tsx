// apps/web/src/features/auth/register.test.tsx
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SafeApiError } from '../../shared/api/safe-error';
import type { RegisterInput } from '../../shared/auth/auth-contract';
import type { SessionOutcome } from '../../shared/auth/session-controller';
import { RegisterPage } from './register-page';
import { registerFormSchema, toRegisterInput } from './register-schema';

const { registerCustomer } = vi.hoisted(() => ({
  registerCustomer: vi.fn<(input: RegisterInput) => Promise<SessionOutcome>>(),
}));

vi.mock('../../shared/auth/session-context', () => ({
  useSession: () => ({
    phase: 'anonymous',
    user: null,
    error: null,
  }),

  useSessionController: () => ({
    register: registerCustomer,
  }),
}));

function renderRegisterPage() {
  return render(
    <MemoryRouter>
      <RegisterPage />
    </MemoryRouter>,
  );
}

function fillRegistrationForm({
  displayName = ' Customer Name ',
  email = ' CUSTOMER@example.test ',
  password = '  secure password  ',
  confirmation = password,
}: {
  readonly displayName?: string;
  readonly email?: string;
  readonly password?: string;
  readonly confirmation?: string;
} = {}) {
  fireEvent.change(screen.getByLabelText(/Display name/i), {
    target: { value: displayName },
  });

  fireEvent.change(screen.getByLabelText('Email address'), {
    target: { value: email },
  });

  fireEvent.change(screen.getByLabelText(/^Password$/), {
    target: { value: password },
  });

  fireEvent.change(screen.getByLabelText('Confirm password'), {
    target: { value: confirmation },
  });
}

beforeEach(() => {
  registerCustomer.mockReset();

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

describe('registration validation', () => {
  it('normalizes customer registration input', () => {
    const values = registerFormSchema.parse({
      display_name: '  Customer Name  ',
      email: ' CUSTOMER@example.test ',
      password: '  password with spaces  ',
      confirm_password: '  password with spaces  ',
    });

    expect(toRegisterInput(values)).toEqual({
      display_name: 'Customer Name',
      email: 'customer@example.test',
      password: '  password with spaces  ',
    });
  });

  it('omits an empty optional display name', () => {
    const values = registerFormSchema.parse({
      display_name: '   ',
      email: 'customer@example.test',
      password: 'password',
      confirm_password: 'password',
    });

    expect(toRegisterInput(values)).toEqual({
      email: 'customer@example.test',
      password: 'password',
    });
  });

  it('requires matching passwords', () => {
    const result = registerFormSchema.safeParse({
      display_name: '',
      email: 'customer@example.test',
      password: 'first-password',
      confirm_password: 'second-password',
    });

    expect(result.success).toBe(false);

    if (!result.success) {
      expect(result.error.flatten().fieldErrors.confirm_password).toContain(
        'The passwords do not match.',
      );
    }
  });

  it('enforces the UTF-8 password byte limit', () => {
    expect(
      registerFormSchema.safeParse({
        display_name: '',
        email: 'customer@example.test',
        password: 'é'.repeat(512),
        confirm_password: 'é'.repeat(512),
      }).success,
    ).toBe(true);

    expect(
      registerFormSchema.safeParse({
        display_name: '',
        email: 'customer@example.test',
        password: 'é'.repeat(513),
        confirm_password: 'é'.repeat(513),
      }).success,
    ).toBe(false);
  });
});

describe('registration form', () => {
  it('renders registration and login navigation', () => {
    renderRegisterPage();

    expect(
      screen.getByRole('heading', {
        name: 'Create your account',
      }),
    ).toBeInTheDocument();

    expect(screen.getByRole('link', { name: 'Sign in instead' })).toHaveAttribute('href', '/login');

    expect(screen.queryByLabelText(/role/i)).not.toBeInTheDocument();
  });

  it('validates empty input without sending a request', async () => {
    renderRegisterPage();

    fireEvent.submit(screen.getByRole('form', { name: 'Create customer account' }));

    expect(await screen.findByText('Enter your email address.')).toBeInTheDocument();
    expect(await screen.findByText('Create a password.')).toBeInTheDocument();
    expect(await screen.findByText('Confirm your password.')).toBeInTheDocument();

    expect(registerCustomer).not.toHaveBeenCalled();
  });

  it('validates mismatched passwords without sending a request', async () => {
    renderRegisterPage();

    fillRegistrationForm({
      password: 'first-password',
      confirmation: 'different-password',
    });

    fireEvent.submit(screen.getByRole('form', { name: 'Create customer account' }));

    expect(await screen.findByText('The passwords do not match.')).toBeInTheDocument();
    expect(registerCustomer).not.toHaveBeenCalled();
  });

  it('submits normalized customer details without a role', async () => {
    registerCustomer.mockResolvedValue({ ok: true });

    renderRegisterPage();
    fillRegistrationForm();

    fireEvent.submit(screen.getByRole('form', { name: 'Create customer account' }));

    await waitFor(() => {
      expect(registerCustomer).toHaveBeenCalledWith({
        display_name: 'Customer Name',
        email: 'customer@example.test',
        password: '  secure password  ',
      });
    });

    const request = registerCustomer.mock.calls[0]?.[0];

    expect(request).not.toHaveProperty('role');

    await waitFor(() => {
      expect(screen.getByLabelText(/^Password$/)).toHaveValue('');
      expect(screen.getByLabelText('Confirm password')).toHaveValue('');
    });
  });

  it('allows both password fields to be revealed independently', () => {
    renderRegisterPage();

    const password = screen.getByLabelText(/^Password$/);
    const confirmation = screen.getByLabelText('Confirm password');

    const visibilityButtons = screen.getAllByRole('button', {
      name: 'Show password',
    });

    const passwordToggle = visibilityButtons[0];
    const confirmationToggle = visibilityButtons[1];

    if (passwordToggle === undefined || confirmationToggle === undefined) {
      throw new Error('Expected password visibility controls to be rendered.');
    }

    expect(password).toHaveAttribute('type', 'password');
    expect(confirmation).toHaveAttribute('type', 'password');

    fireEvent.click(passwordToggle);

    expect(password).toHaveAttribute('type', 'text');
    expect(confirmation).toHaveAttribute('type', 'password');
    expect(passwordToggle).toHaveAccessibleName('Hide password');

    fireEvent.click(confirmationToggle);

    expect(password).toHaveAttribute('type', 'text');
    expect(confirmation).toHaveAttribute('type', 'text');
    expect(confirmationToggle).toHaveAccessibleName('Hide password');

    fireEvent.click(passwordToggle);

    expect(password).toHaveAttribute('type', 'password');
    expect(confirmation).toHaveAttribute('type', 'text');
    expect(passwordToggle).toHaveAccessibleName('Show password');
  });

  it('shows a safe duplicate-email error', async () => {
    registerCustomer.mockResolvedValue({
      ok: false,
      reason: 'request-failed',
      error: SafeApiError.fromHttp(409, null),
      retryAfterMs: null,
    });

    renderRegisterPage();
    fillRegistrationForm();

    fireEvent.submit(screen.getByRole('form', { name: 'Create customer account' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'An account with this email address already exists.',
    );

    await waitFor(() => {
      expect(screen.getByLabelText(/^Password$/)).toHaveValue('');
      expect(screen.getByLabelText('Confirm password')).toHaveValue('');
    });
  });

  it('shows a safe password-policy error', async () => {
    registerCustomer.mockResolvedValue({
      ok: false,
      reason: 'request-failed',
      error: SafeApiError.fromHttp(400, null),
      retryAfterMs: null,
    });

    renderRegisterPage();
    fillRegistrationForm();

    fireEvent.submit(screen.getByRole('form', { name: 'Create customer account' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This password does not satisfy the account security requirements.',
    );
  });

  it('shows a safe network error', async () => {
    registerCustomer.mockResolvedValue({
      ok: false,
      reason: 'request-failed',
      error: SafeApiError.fromLocal('network'),
      retryAfterMs: null,
    });

    renderRegisterPage();
    fillRegistrationForm();

    fireEvent.submit(screen.getByRole('form', { name: 'Create customer account' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Registration could not reach the service.',
    );
  });

  it('prevents duplicate submissions while registration is pending', async () => {
    let finish!: (outcome: SessionOutcome) => void;

    registerCustomer.mockReturnValue(
      new Promise<SessionOutcome>((resolve) => {
        finish = resolve;
      }),
    );

    renderRegisterPage();
    fillRegistrationForm();

    const form = screen.getByRole('form', {
      name: 'Create customer account',
    });

    fireEvent.submit(form);

    await waitFor(() => {
      expect(registerCustomer).toHaveBeenCalledTimes(1);
    });

    fireEvent.submit(form);

    expect(
      screen.getByRole('button', {
        name: 'Creating your account…',
      }),
    ).toBeDisabled();

    await act(async () => {
      finish({ ok: true });
    });

    expect(registerCustomer).toHaveBeenCalledTimes(1);
  });
});
