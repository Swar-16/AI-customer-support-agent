// apps/web/src/app/application-router.tsx

import { lazy, Suspense } from 'react';
import type { ReactNode } from 'react';
import {
  createBrowserRouter,
  Link,
  Navigate,
  Route,
  RouterProvider,
  Routes,
  useLocation,
} from 'react-router';

import { useSession } from '../shared/auth/session-context';
import { canOpenWorkspace, homePath } from '../shared/auth/workspace-access';
import type { Workspace } from '../shared/auth/workspace-access';
import { LoginPage } from '../features/auth/login-page';
import { LogoutPage } from '../features/auth/logout-page';
import { RegisterPage } from '../features/auth/register-page';
import { loginDestination } from '../features/auth/login-destination';
import { RouteErrorBoundary } from './route-error-boundary';
import { LogoutDialogProvider } from '../features/auth/logout-dialog';
import { NavigationProtectionProvider } from '../shared/navigation/navigation-protection-provider';
import { ChatNavigationGuard } from '../features/chat/chat-navigation-guard';

const ChatPage = lazy(() => import('../features/chat/chat-page'));
const OperationsPage = lazy(() => import('../features/operations/operations-page'));
const KnowledgePage = lazy(() => import('../features/knowledge/knowledge-page'));

const KnowledgeLibrary = lazy(() =>
  import('../features/knowledge/knowledge-library').then((module) => ({
    default: module.KnowledgeLibrary,
  })),
);

const KnowledgeDocumentDetail = lazy(() =>
  import('../features/knowledge/knowledge-document-detail').then((module) => ({
    default: module.KnowledgeDocumentDetail,
  })),
);

const KnowledgeVersionDetail = lazy(() =>
  import('../features/knowledge/knowledge-version-detail').then((module) => ({
    default: module.KnowledgeVersionDetail,
  })),
);

function Notice({ title, children }: { readonly title: string; readonly children: ReactNode }) {
  return (
    <main className="foundation-screen" aria-labelledby="route-notice-title">
      <section className="foundation-panel">
        <h1 id="route-notice-title">{title}</h1>
        {children}
      </section>
    </main>
  );
}

function SessionPending() {
  return (
    <Notice title="Checking your session">
      <p role="status">Please wait while your session is checked.</p>
    </Notice>
  );
}

function Home() {
  const session = useSession();

  if (session.phase === 'uninitialized' || session.phase === 'pending') {
    return <SessionPending />;
  }

  const destination = session.phase === 'authenticated' ? homePath(session.user) : null;

  return <Navigate to={destination ?? '/login'} replace />;
}

function RegisterEntry() {
  const session = useSession();

  if (session.phase === 'authenticated') {
    const destination = homePath(session.user);

    if (destination !== null) {
      return <Navigate to={destination} replace />;
    }

    /*
     * Defensive fallback. The session controller normally prevents unsupported or inactive accounts from becoming authenticated.
     */
    return (
      <Notice title="No workspace is available">
        <p role="alert">This account does not have access to an application workspace.</p>
        <Link to="/logout">Sign out</Link>
      </Notice>
    );
  }

  return <RegisterPage />;
}

function LoginEntry() {
  const session = useSession();
  const location = useLocation();

  const destination =
    session.phase === 'authenticated' ? loginDestination(location.state, session.user) : null;

  if (destination !== null) {
    return <Navigate to={destination} replace />;
  }

  // Keep the form mounted during pending requests so its form state and
  // server-error handling survive the controller's state transitions.
  return <LoginPage />;
}

function RequireWorkspace({
  workspace,
  children,
}: {
  readonly workspace: Workspace;
  readonly children: ReactNode;
}) {
  const session = useSession();
  const location = useLocation();

  if (session.phase === 'uninitialized' || session.phase === 'pending') {
    return <SessionPending />;
  }

  if (session.phase === 'anonymous') {
    const workspaceRoot = `/${workspace}`;

    /*
     * Preserve only a path that belongs to the requested workspace. Query strings, hashes, and external URLs are deliberately excluded.
     */
    const returnTo =
      location.pathname === workspaceRoot || location.pathname.startsWith(`${workspaceRoot}/`)
        ? location.pathname
        : workspaceRoot;

    return <Navigate to="/login" replace state={{ returnTo }} />;
  }

  if (session.phase !== 'authenticated' || session.user === null) {
    return (
      <Notice title="Your session is unavailable">
        <p role="alert">Your session could not be verified or changed in another tab.</p>
        <Link to="/login">Go to sign-in</Link>
      </Notice>
    );
  }

  if (!canOpenWorkspace(session.user, workspace)) {
    return (
      <Notice title="This workspace is not available to your account">
        <p>You do not have access to this workspace.</p>
        <Link to="/">Go to your workspace</Link>
      </Notice>
    );
  }

  return children;
}

export function ApplicationRoutes({
  enableNavigationGuard = false,
}: {
  readonly enableNavigationGuard?: boolean;
}) {
  const location = useLocation();

  return (
    <NavigationProtectionProvider>
      <LogoutDialogProvider>
        {enableNavigationGuard && <ChatNavigationGuard />}
        <RouteErrorBoundary key={location.pathname}>
          <Suspense
            fallback={
              <Notice title="Opening workspace">
                <p role="status">Loading the application screen…</p>
              </Notice>
            }
          >
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/login" element={<LoginEntry />} />
              <Route path="/register" element={<RegisterEntry />} />
              <Route path="/logout" element={<LogoutPage />} />

              <Route
                path="/chat"
                element={
                  <RequireWorkspace workspace="chat">
                    <ChatPage />
                  </RequireWorkspace>
                }
              />
              <Route
                path="/chat/:conversationId"
                element={
                  <RequireWorkspace workspace="chat">
                    <ChatPage />
                  </RequireWorkspace>
                }
              />

              <Route
                path="/operations/*"
                element={
                  <RequireWorkspace workspace="operations">
                    <OperationsPage />
                  </RequireWorkspace>
                }
              />

              <Route
                path="/knowledge"
                element={
                  <RequireWorkspace workspace="knowledge">
                    <KnowledgePage />
                  </RequireWorkspace>
                }
              >
                <Route index element={<KnowledgeLibrary />} />

                <Route path="documents/:documentId" element={<KnowledgeDocumentDetail />} />

                <Route
                  path="documents/:documentId/versions/:versionId"
                  element={<KnowledgeVersionDetail />}
                />
              </Route>

              <Route
                path="*"
                element={
                  <Notice title="Page not found">
                    <p>This address does not match an available page.</p>
                    <Link to="/">Go to your workspace</Link>
                  </Notice>
                }
              />
            </Routes>
          </Suspense>
        </RouteErrorBoundary>
      </LogoutDialogProvider>
    </NavigationProtectionProvider>
  );
}

// Create once, outside React rendering.
const applicationRouter = createBrowserRouter([
  {
    path: '*',
    element: <ApplicationRoutes enableNavigationGuard />,
  },
]);

// Release the previous router when Vite replaces this module.
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    applicationRouter.dispose();
  });
}

export function ApplicationRouter() {
  return <RouterProvider router={applicationRouter} />;
}
