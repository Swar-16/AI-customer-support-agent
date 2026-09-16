// apps/web/src/features/auth/logout-dialog.tsx
import { createContext, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Link, useNavigate } from 'react-router';
import { Check, LoaderCircle, LogOut, X } from 'lucide-react';

import { useSession, useSessionController } from '../../shared/auth/session-context';

import './logout-dialog.css';

type DialogState = 'idle' | 'pending' | 'confirmed' | 'unconfirmed';

const LogoutDialogContext = createContext<(() => void) | null>(null);

export function useLogoutDialog(): () => void {
  const requestLogout = useContext(LogoutDialogContext);

  if (requestLogout === null) {
    throw new Error('LogoutDialogProvider is required.');
  }

  return requestLogout;
}

export function LogoutDialogProvider({ children }: { readonly children: ReactNode }) {
  const session = useSession();
  const controller = useSessionController();
  const navigate = useNavigate();

  const [state, setState] = useState<DialogState | null>(null);

  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const inFlightRef = useRef(false);
  const mountedRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (state === null) return;

    const dialog = dialogRef.current;
    if (!dialog) return;

    if (!dialog.open) {
      dialog.showModal();
    }

    if (state === 'idle') {
      cancelRef.current?.focus();
    } else if (state === 'confirmed' || state === 'unconfirmed') {
      headingRef.current?.focus();
    }
  }, [state]);

  useEffect(() => {
    if (state !== 'confirmed') return;

    const timer = window.setTimeout(() => {
      dialogRef.current?.close();
      setState(null);
      void navigate('/login', { replace: true });
    }, 2500);

    return () => window.clearTimeout(timer);
  }, [state, navigate]);

  function requestLogout() {
    if (state !== null || inFlightRef.current || session.phase !== 'authenticated') {
      return;
    }

    triggerRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    setState('idle');
  }

  function dismiss() {
    if (state !== 'idle' || inFlightRef.current) return;

    dialogRef.current?.close();
    setState(null);

    if (triggerRef.current?.isConnected) {
      triggerRef.current.focus({ preventScroll: true });
    }
  }

  async function confirmLogout() {
    if (state !== 'idle' || inFlightRef.current || session.phase !== 'authenticated') {
      return;
    }

    inFlightRef.current = true;
    setState('pending');

    try {
      const result = await controller.logout();

      if (mountedRef.current) {
        setState(result.ok ? 'confirmed' : 'unconfirmed');
      }
    } catch {
      if (mountedRef.current) {
        setState('unconfirmed');
      }
    } finally {
      inFlightRef.current = false;
    }
  }

  function finish() {
    dialogRef.current?.close();
    setState(null);
  }

  const title =
    state === 'confirmed'
      ? 'You are signed out'
      : state === 'unconfirmed'
        ? 'Sign-out could not be confirmed'
        : 'Sign out?';

  return (
    <LogoutDialogContext.Provider value={requestLogout}>
      {children}

      {state !== null &&
        createPortal(
          <dialog
            ref={dialogRef}
            className="logout-dialog"
            aria-labelledby="logout-dialog-title"
            aria-describedby="logout-dialog-description"
            aria-modal="true"
            aria-busy={state === 'pending'}
            onCancel={(event) => {
              event.preventDefault();
              dismiss();
            }}
          >
            <div className="logout-dialog__top">
              <span className="logout-dialog__emblem" aria-hidden="true">
                {state === 'confirmed' ? <Check size={26} /> : <LogOut size={26} />}
              </span>

              {state === 'idle' && (
                <button
                  className="logout-dialog__dismiss"
                  type="button"
                  aria-label="Dismiss sign-out confirmation"
                  onClick={dismiss}
                >
                  <X size={20} aria-hidden="true" />
                </button>
              )}
            </div>

            <h2 id="logout-dialog-title" ref={headingRef} tabIndex={-1}>
              {title}
            </h2>

            <p id="logout-dialog-description">
              {state === 'confirmed'
                ? 'Your session has ended. Taking you to sign in…'
                : state === 'unconfirmed'
                  ? 'We could not confirm that the server session and browser refresh cookie were cleared.'
                  : 'You’ll need to sign in again to return to your workspace.'}
            </p>

            {state === 'unconfirmed' && (
              <p className="logout-dialog__notice" role="alert">
                Sign-out has not been confirmed. No automatic retry was made.
              </p>
            )}

            <p className="logout-dialog__notice" role="status" aria-atomic="true">
              {state === 'pending'
                ? 'Waiting for sign-out confirmation…'
                : state === 'confirmed'
                  ? 'Redirecting to sign in in a moment.'
                  : state === 'idle' && session.phase !== 'authenticated'
                    ? 'Your session changed. Dismiss this dialog to continue.'
                    : ''}
            </p>

            <div className="logout-dialog__actions">
              {state === 'idle' || state === 'pending' ? (
                <>
                  <button
                    ref={cancelRef}
                    type="button"
                    className="logout-dialog__action logout-dialog__action--outline"
                    disabled={state === 'pending'}
                    onClick={dismiss}
                  >
                    Stay here
                  </button>

                  <button
                    type="button"
                    className="logout-dialog__action logout-dialog__action--solid"
                    disabled={state === 'pending' || session.phase !== 'authenticated'}
                    onClick={() => {
                      void confirmLogout();
                    }}
                  >
                    {state === 'pending' ? (
                      <LoaderCircle
                        size={18}
                        className="logout-dialog__spinner"
                        aria-hidden="true"
                      />
                    ) : (
                      <LogOut size={18} aria-hidden="true" />
                    )}

                    {state === 'pending' ? 'Signing out…' : 'Confirm sign out'}
                  </button>
                </>
              ) : (
                <Link
                  to="/login"
                  replace
                  className="logout-dialog__action logout-dialog__action--solid"
                  onClick={finish}
                >
                  {state === 'confirmed' ? 'Return to sign-in' : 'Go to sign-in'}
                </Link>
              )}
            </div>
          </dialog>,
          document.body,
        )}
    </LogoutDialogContext.Provider>
  );
}
