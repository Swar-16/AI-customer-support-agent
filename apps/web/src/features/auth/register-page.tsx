// apps/web/src/features/auth/register-page.tsx
import { zodResolver } from '@hookform/resolvers/zod';
import { Eye, EyeOff, UserRoundPlus } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link } from 'react-router';

import { useSession, useSessionController } from '../../shared/auth/session-context';
import type { SessionOutcome } from '../../shared/auth/session-controller';
import { identity } from '../../shared/branding/identity';
import { LoginAtmosphere } from './login-atmosphere';
import { registerFormSchema, toRegisterInput, type RegisterFormValues } from './register-schema';

import './login-page.css';

function registrationFailureMessage(
  outcome: Exclude<SessionOutcome, { readonly ok: true }>,
): string {
  switch (outcome.reason) {
    case 'busy':
      return 'Another account operation is already in progress. Please wait.';

    case 'reauthentication-required':
      return 'Your session could not be prepared. Please refresh the page and try again.';

    case 'unsupported-account':
      return 'The account was created, but it cannot access the customer application.';

    case 'session-changed':
      return 'Your session changed in another tab. Please refresh the page before trying again.';

    case 'logout-unconfirmed':
      return 'The account operation could not be confirmed.';

    case 'request-failed':
      if (outcome.error.status === 409) {
        return 'An account with this email address already exists.';
      }

      if (outcome.error.status === 400) {
        return 'This password does not satisfy the account security requirements.';
      }

      if (outcome.error.status === 403) {
        return 'Registration is not available from this application origin.';
      }

      if (outcome.error.status === 422) {
        return 'Some account details could not be accepted. Review the form and try again.';
      }

      if (outcome.error.kind === 'timeout') {
        return 'Registration took too long to complete. Check your connection and try again.';
      }

      if (outcome.error.kind === 'network') {
        return 'Registration could not reach the service. Check your connection and try again.';
      }

      return outcome.error.message;
  }
}

interface PasswordVisibilityButtonProps {
  readonly visible: boolean;
  readonly controls: string;
  readonly disabled: boolean;
  readonly onToggle: () => void;
}

function PasswordVisibilityButton({
  visible,
  controls,
  disabled,
  onToggle,
}: PasswordVisibilityButtonProps) {
  const label = visible ? 'Hide password' : 'Show password';
  const Icon = visible ? EyeOff : Eye;

  return (
    <button
      type="button"
      className="login-page__password-toggle"
      aria-label={label}
      aria-controls={controls}
      aria-pressed={visible}
      title={label}
      disabled={disabled}
      onClick={onToggle}
    >
      <Icon size={18} aria-hidden="true" />
    </button>
  );
}

export function RegisterPage() {
  const session = useSession();
  const controller = useSessionController();
  const submissionInFlight = useRef(false);

  const [passwordVisible, setPasswordVisible] = useState(false);
  const [confirmationVisible, setConfirmationVisible] = useState(false);

  const {
    register,
    handleSubmit,
    resetField,
    setError,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerFormSchema),
    defaultValues: {
      display_name: '',
      email: '',
      password: '',
      confirm_password: '',
    },
    mode: 'onSubmit',
    reValidateMode: 'onChange',
  });

  useEffect(() => {
    document.title = `Create account · ${identity.productName}`;
  }, []);

  const sessionPending = session.phase === 'uninitialized' || session.phase === 'pending';
  const busy = isSubmitting || sessionPending;

  async function submit(values: RegisterFormValues) {
    clearErrors('root');

    try {
      const outcome = await controller.register(toRegisterInput(values));

      if (!outcome.ok) {
        setError('root.server', {
          type: 'server',
          message: registrationFailureMessage(outcome),
        });
      }
    } catch {
      setError('root.server', {
        type: 'server',
        message: 'Your account could not be created. Please try again.',
      });
    } finally {
      /*
       * Passwords are never retained after a registration request,
       * regardless of whether the request succeeds or fails.
       */
      resetField('password');
      resetField('confirm_password');

      setPasswordVisible(false);
      setConfirmationVisible(false);
    }
  }

  const passwordDescription = [
    'register-password-hint',
    errors.password ? 'register-password-error' : null,
  ]
    .filter((value): value is string => value !== null)
    .join(' ');

  return (
    <main
      className="login-page login-page--immersive login-page--register"
      aria-labelledby="register-title"
    >
      <LoginAtmosphere />

      <section className="login-page__panel">
        <div className="login-page__brand">
          <svg width="32" height="32" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
            <path
              fill="currentColor"
              d="M24 2C27 17 31 21 46 24C31 27 27 31 24 46C21 31 17 27 2 24C17 21 21 17 24 2Z"
            />
          </svg>

          <span>{identity.productName}</span>
        </div>

        <div className="login-page__heading">
          <span className="login-page__heading-icon" aria-hidden="true">
            <UserRoundPlus size={20} />
          </span>

          <div>
            <p className="login-page__eyebrow">Customer access</p>
            <h1 id="register-title">Create your account</h1>
          </div>
        </div>

        <p className="login-page__intro">
          Start a secure support workspace where your conversations remain organized and easy to
          revisit.
        </p>

        <form
          aria-label="Create customer account"
          noValidate
          aria-busy={busy}
          onSubmit={(event) => {
            event.preventDefault();

            if (submissionInFlight.current || sessionPending) {
              return;
            }

            /*
             * Lock synchronously before asynchronous validation begins.
             * This prevents rapid repeated submissions from creating
             * multiple registration requests.
             */
            submissionInFlight.current = true;

            void handleSubmit(submit)(event)
              .catch(() => {
                setError('root.server', {
                  type: 'server',
                  message: 'Your account could not be created. Please try again.',
                });
              })
              .finally(() => {
                submissionInFlight.current = false;
              });
          }}
        >
          <fieldset disabled={busy}>
            <legend className="login-page__visually-hidden">Customer account details</legend>

            <div className="login-page__field">
              <label htmlFor="register-display-name">
                Display name
                <span className="login-page__optional">Optional</span>
              </label>

              <input
                id="register-display-name"
                type="text"
                autoComplete="name"
                placeholder="How should we address you?"
                aria-invalid={Boolean(errors.display_name)}
                aria-describedby={errors.display_name ? 'register-display-name-error' : undefined}
                {...register('display_name')}
              />

              {errors.display_name && (
                <p id="register-display-name-error" className="login-page__error" role="alert">
                  {errors.display_name.message}
                </p>
              )}
            </div>

            <div className="login-page__field">
              <label htmlFor="register-email">Email address</label>

              <input
                id="register-email"
                type="email"
                inputMode="email"
                autoComplete="email"
                autoCapitalize="none"
                spellCheck={false}
                placeholder="you@example.com"
                aria-invalid={Boolean(errors.email)}
                aria-describedby={errors.email ? 'register-email-error' : undefined}
                {...register('email')}
              />

              {errors.email && (
                <p id="register-email-error" className="login-page__error" role="alert">
                  {errors.email.message}
                </p>
              )}
            </div>

            <div className="login-page__field">
              <label htmlFor="register-password">Password</label>

              <div className="login-page__password-control">
                <input
                  id="register-password"
                  type={passwordVisible ? 'text' : 'password'}
                  autoComplete="new-password"
                  placeholder="Create a secure password"
                  aria-invalid={Boolean(errors.password)}
                  aria-describedby={passwordDescription}
                  {...register('password')}
                />

                <PasswordVisibilityButton
                  visible={passwordVisible}
                  controls="register-password"
                  disabled={busy}
                  onToggle={() => {
                    setPasswordVisible((current) => !current);
                  }}
                />
              </div>

              <p id="register-password-hint" className="login-page__hint">
                Use a strong password that you do not use for another account.
              </p>

              {errors.password && (
                <p id="register-password-error" className="login-page__error" role="alert">
                  {errors.password.message}
                </p>
              )}
            </div>

            <div className="login-page__field">
              <label htmlFor="register-confirm-password">Confirm password</label>

              <div className="login-page__password-control">
                <input
                  id="register-confirm-password"
                  type={confirmationVisible ? 'text' : 'password'}
                  autoComplete="new-password"
                  placeholder="Enter the password again"
                  aria-invalid={Boolean(errors.confirm_password)}
                  aria-describedby={
                    errors.confirm_password ? 'register-confirm-password-error' : undefined
                  }
                  {...register('confirm_password')}
                />

                <PasswordVisibilityButton
                  visible={confirmationVisible}
                  controls="register-confirm-password"
                  disabled={busy}
                  onToggle={() => {
                    setConfirmationVisible((current) => !current);
                  }}
                />
              </div>

              {errors.confirm_password && (
                <p id="register-confirm-password-error" className="login-page__error" role="alert">
                  {errors.confirm_password.message}
                </p>
              )}
            </div>

            <button className="login-page__primary-action" type="submit" disabled={busy}>
              <span>{isSubmitting ? 'Creating your account…' : 'Create account'}</span>
            </button>
          </fieldset>

          <div className="login-page__feedback">
            {errors.root?.server?.message && (
              <p role="alert" className="login-page__error login-page__server-error">
                {errors.root.server.message}
              </p>
            )}

            <p role="status">
              {isSubmitting
                ? 'Creating your secure customer workspace…'
                : sessionPending
                  ? 'Checking your session…'
                  : ''}
            </p>
          </div>
        </form>

        <div className="login-page__account-switch">
          <span>Already have an account?</span>

          <Link to="/login">Sign in instead</Link>
        </div>

        <p className="login-page__security-note">
          Customer registration never grants administrative or support-agent access.
        </p>
      </section>
    </main>
  );
}
