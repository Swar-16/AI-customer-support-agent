// apps/web/src/features/auth/logout-page.tsx

import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import { useSession, useSessionController } from '../../shared/auth/session-context';
import { homePath } from '../../shared/auth/workspace-access';
import { identity } from '../../shared/branding/identity';

import './login-page.css';

type LogoutState = 'idle' | 'pending' | 'confirmed' | 'unconfirmed';

export function LogoutPage() {
  const session = useSession();
  const controller = useSessionController();
  const navigate = useNavigate();
  const [state, setState] = useState<LogoutState>('idle');
  const inFlight = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    document.title = `Sign out · ${identity.productName}`;
    heading.current?.focus();
  }, []);

  useEffect(() => {
    if (state !== 'confirmed') return;

    const timeoutId = window.setTimeout(() => {
      void navigate('/login', { replace: true });
    }, 100);

    return () => window.clearTimeout(timeoutId);
  }, [state, navigate]);

  const pending = state === 'pending';
  const confirmed = state === 'confirmed';
  const unconfirmed = state === 'unconfirmed';
  const canSubmit = state === 'idle' && session.phase === 'authenticated';

  const destination = session.phase === 'authenticated' ? homePath(session.user) : null;

  async function signOut() {
    if (inFlight.current || !canSubmit) return;

    inFlight.current = true;
    setState('pending');

    try {
      const outcome = await controller.logout();
      setState(outcome.ok ? 'confirmed' : 'unconfirmed');
    } catch {
      setState('unconfirmed');
    } finally {
      inFlight.current = false;
    }
  }

  const title = confirmed
    ? 'You are signed out'
    : unconfirmed
      ? 'Sign-out could not be confirmed'
      : 'Sign out';

  return (
    <main className="login-page" aria-labelledby="logout-title">
      <section className="login-page__panel">
        <p className="login-page__brand">{identity.productName}</p>

        <h1 id="logout-title" ref={heading} tabIndex={-1}>
          {title}
        </h1>

        {confirmed ? (
          <>
            <p className="login-page__intro" role="status">
              You have been signed out. Redirecting you to sign in…
            </p>
            <Link to="/login" replace>
              Return to sign-in
            </Link>
          </>
        ) : unconfirmed ? (
          <>
            <p className="login-page__intro" role="alert">
              We could not confirm that the server session and browser refresh cookie were cleared.
              You have not been shown a successful sign-out.
            </p>
            <Link to="/login" replace>
              Go to sign-in
            </Link>
          </>
        ) : (
          <>
            <p className="login-page__intro">Sign out of the current browser session.</p>

            {(canSubmit || pending) && (
              <button
                type="button"
                disabled={pending}
                onClick={() => {
                  void signOut();
                }}
              >
                {pending ? 'Signing out…' : 'Confirm sign out'}
              </button>
            )}

            <div className="login-page__feedback">
              <p role="status">
                {pending
                  ? 'Waiting for sign-out confirmation…'
                  : session.phase === 'uninitialized' || session.phase === 'pending'
                    ? 'A session operation is in progress.'
                    : session.phase === 'anonymous'
                      ? 'There is no active session in this tab.'
                      : session.phase === 'unavailable'
                        ? 'The session is unavailable. Server sign-out has not been confirmed.'
                        : ''}
              </p>
            </div>

            {!pending && (
              <Link to={destination ?? '/login'}>
                {destination === null ? 'Go to sign-in' : 'Back to workspace'}
              </Link>
            )}
          </>
        )}
      </section>
    </main>
  );
}
