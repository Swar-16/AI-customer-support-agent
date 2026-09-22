// apps/web/src/features/auth/login-page.tsx

import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect, useRef } from 'react';
import { useForm } from 'react-hook-form';
import { Link } from 'react-router';

import type { LoginInput } from '../../shared/auth/auth-contract';
import { useSession, useSessionController } from '../../shared/auth/session-context';
import type { SessionOutcome } from '../../shared/auth/session-controller';
import { identity } from '../../shared/branding/identity';
import { loginSchema } from './login-schema';
import { LoginAtmosphere } from './login-atmosphere';

import './login-page.css';

function failureMessage(outcome: Exclude<SessionOutcome, { readonly ok: true }>): string {
  switch (outcome.reason) {
    case 'busy':
      return 'Another sign-in operation is in progress. Please wait.';
    case 'reauthentication-required':
      return 'Please sign in again.';
    case 'unsupported-account':
      return 'This account cannot access the interactive application.';
    case 'session-changed':
      return 'Your session changed in another tab. Please sign in again.';
    case 'logout-unconfirmed':
      return 'Sign-out could not be confirmed.';
    case 'request-failed':
      if (outcome.error.status === 401) {
        return 'Sign-in failed. Check your email and password.';
      }
      if (outcome.error.kind === 'timeout' || outcome.error.kind === 'network') {
        return 'Sign-in could not be confirmed. Check your connection before trying again.';
      }
      return outcome.error.message;
  }
}

export function LoginPage() {
  const session = useSession();
  const controller = useSessionController();
  const inFlight = useRef(false);

  const {
    register,
    handleSubmit,
    resetField,
    setError,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm<LoginInput>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
    mode: 'onSubmit',
    reValidateMode: 'onChange',
  });

  useEffect(() => {
    document.title = `Sign in · ${identity.productName}`;
  }, []);

  const sessionPending = session.phase === 'uninitialized' || session.phase === 'pending';

  const busy = isSubmitting || sessionPending;

  async function submit(values: LoginInput) {
    // if (inFlight.current || sessionPending) return;

    // inFlight.current = true;
    clearErrors('root');

    try {
      const outcome = await controller.login(values);

      if (!outcome.ok) {
        setError('root.server', {
          type: 'server',
          message: failureMessage(outcome),
        });
      }
    } catch {
      setError('root.server', {
        type: 'server',
        message: 'Sign-in could not be completed.',
      });
    } finally {
      // Do not retain the submitted password after the request finishes.
      resetField('password');
      //   inFlight.current = false;
    }
  }

  return (
    <main className="login-page login-page--immersive" aria-labelledby="login-title">
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

        <h1 id="login-title">Sign in</h1>
        <p className="login-page__intro">Continue to your support workspace.</p>

        <form
          aria-label="Sign in"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();

            if (inFlight.current || sessionPending) return;

            // Lock synchronously, before asynchronous form validation.
            inFlight.current = true;

            void handleSubmit(submit)(event)
              .catch(() => {
                setError('root.server', {
                  type: 'server',
                  message: 'Sign-in could not be completed.',
                });
              })
              .finally(() => {
                // Release after validation and submission have both finished.
                inFlight.current = false;
              });
          }}
          aria-busy={busy}
        >
          <fieldset disabled={busy}>
            <legend className="login-page__visually-hidden">Account credentials</legend>

            <div className="login-page__field">
              <label htmlFor="login-email">Email address</label>
              <input
                id="login-email"
                type="email"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                aria-invalid={Boolean(errors.email)}
                aria-describedby={errors.email ? 'login-email-error' : undefined}
                {...register('email')}
              />
              {errors.email && (
                <p id="login-email-error" className="login-page__error">
                  {errors.email.message}
                </p>
              )}
            </div>

            <div className="login-page__field">
              <label htmlFor="login-password">Password</label>
              <input
                id="login-password"
                type="password"
                autoComplete="current-password"
                aria-invalid={Boolean(errors.password)}
                aria-describedby={errors.password ? 'login-password-error' : undefined}
                {...register('password')}
              />
              {errors.password && (
                <p id="login-password-error" className="login-page__error">
                  {errors.password.message}
                </p>
              )}
            </div>

            <button className="login-page__primary-action" type="submit" disabled={busy}>
              <span>{isSubmitting ? 'Signing in…' : 'Sign in'}</span>
            </button>
          </fieldset>

          <div className="login-page__feedback">
            {errors.root?.server?.message && (
              <p role="alert" className="login-page__error login-page__server-error">
                {errors.root.server.message}
              </p>
            )}

            <p role="status">
              {isSubmitting ? 'Signing in…' : sessionPending ? 'Checking your session…' : ''}
            </p>
          </div>
        </form>

        <div className="login-page__account-switch">
          <span>New to {identity.productName}?</span>

          <Link to="/register">Create an account</Link>
        </div>
      </section>
    </main>
  );
}
