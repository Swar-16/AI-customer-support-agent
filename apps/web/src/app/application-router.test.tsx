// apps/web/src/app/application-router.test.tsx

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuthUser } from '../shared/auth/auth-contract';
import { useSession } from '../shared/auth/session-context';
import type { SessionSnapshot } from '../shared/auth/session-controller';
import { ApplicationRoutes } from './application-router';

vi.mock('../shared/auth/session-context', () => ({
  useSession: vi.fn(),
  useSessionController: () => ({
    login: vi.fn(),
    register: vi.fn(),
  }),
}));

vi.mock('../features/chat/chat-page', async () => {
  const { WorkspaceEntry } = await import('../shared/components/workspace-entry');

  return {
    default: function ChatRouteFixture() {
      return <WorkspaceEntry workspace="chat" description="Customer workspace route fixture." />;
    },
  };
});

vi.mock('../features/operations/operations-page', () => ({
  default: function OperationsRouteFixture() {
    return (
      <main>
        <h1>Operations</h1>
      </main>
    );
  },
}));

vi.mock('../features/knowledge/knowledge-page', async () => {
  const { NavLink, Outlet } = await import('react-router');

  return {
    default: function KnowledgeRouteFixture() {
      return (
        <main>
          <h1>Knowledge</h1>

          <nav aria-label="Workspace navigation">
            <NavLink to="/operations">Operations</NavLink>
            <NavLink to="/knowledge" end>
              Knowledge
            </NavLink>
          </nav>

          <Outlet />
        </main>
      );
    },
  };
});

vi.mock('../features/knowledge/knowledge-library', () => ({
  KnowledgeLibrary: function KnowledgeLibraryFixture() {
    return <section aria-label="Knowledge library fixture" />;
  },
}));

function authenticated(role: AuthUser['role']): SessionSnapshot {
  return {
    phase: 'authenticated',
    error: null,
    user: {
      id: 'd44e99cb-8e10-4af8-9bb7-c4d293042943',
      email: 'person@example.test',
      display_name: null,
      role,
      status: 'active',
      created_at: '2026-09-15T10:00:00Z',
    },
  };
}

function open(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ApplicationRoutes />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(useSession).mockReturnValue({
    phase: 'anonymous',
    user: null,
    error: null,
  });
});

describe('application routes', () => {
  it('redirects an anonymous visitor to sign-in', async () => {
    open('/knowledge');

    expect(
      await screen.findByRole('heading', {
        name: 'Sign in',
      }),
    ).toBeInTheDocument();
  });

  it('does not render a workspace while checking the session', () => {
    vi.mocked(useSession).mockReturnValue({
      phase: 'pending',
      user: null,
      error: null,
    });

    open('/chat');

    expect(screen.getByRole('status')).toHaveTextContent(
      'Please wait while your session is checked.',
    );
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

  it('opens customer chat without staff navigation', async () => {
    vi.mocked(useSession).mockReturnValue(authenticated('customer'));
    open('/');

    expect(
      await screen.findByRole('heading', { name: 'Customer Chat', level: 1 }),
    ).toBeInTheDocument();

    expect(screen.queryByRole('link', { name: 'Operations' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Knowledge' })).toBeNull();
  });

  it('opens Operations for support agents without Knowledge navigation', async () => {
    vi.mocked(useSession).mockReturnValue(authenticated('support_agent'));
    open('/operations');

    expect(
      await screen.findByRole('heading', { name: 'Operations', level: 1 }),
    ).toBeInTheDocument();

    expect(screen.queryByRole('link', { name: 'Knowledge' })).toBeNull();
  });

  it('allows admins to navigate between Operations and Knowledge', async () => {
    vi.mocked(useSession).mockReturnValue(authenticated('admin'));
    open('/knowledge');

    expect(await screen.findByRole('heading', { name: 'Knowledge', level: 1 })).toBeInTheDocument();

    expect(screen.getByRole('link', { name: 'Operations' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Knowledge' })).toHaveAttribute('aria-current', 'page');
  });

  it.each([
    ['customer', '/operations'],
    ['support_agent', '/knowledge'],
    ['admin', '/chat'],
    ['system', '/knowledge'],
  ] as const)('denies %s access to %s', (role, path) => {
    vi.mocked(useSession).mockReturnValue(authenticated(role));
    open(path);

    expect(
      screen.getByRole('heading', {
        name: 'This workspace is not available to your account',
      }),
    ).toBeInTheDocument();
  });

  it('removes workspace content when the session becomes unavailable', async () => {
    vi.mocked(useSession).mockReturnValue(authenticated('customer'));
    const view = open('/chat');

    await screen.findByRole('heading', { name: 'Customer Chat', level: 1 });

    vi.mocked(useSession).mockReturnValue({
      phase: 'unavailable',
      user: null,
      error: null,
    });

    view.rerender(
      <MemoryRouter initialEntries={['/chat']}>
        <ApplicationRoutes />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole('heading', { name: 'Your session is unavailable' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('shows not found for an unknown knowledge route', async () => {
    vi.mocked(useSession).mockReturnValue(authenticated('admin'));

    open('/knowledge/not-implemented');

    expect(
      await screen.findByRole('heading', {
        name: 'Page not found',
      }),
    ).toBeInTheDocument();
  });

  it('opens public customer registration for an anonymous visitor', async () => {
    open('/register');

    expect(
      await screen.findByRole('heading', {
        name: 'Create your account',
      }),
    ).toBeInTheDocument();

    expect(screen.getByRole('link', { name: 'Sign in instead' })).toHaveAttribute('href', '/login');
  });

  it('links sign-in to public registration', async () => {
    open('/login');

    expect(
      await screen.findByRole('heading', {
        name: 'Sign in',
      }),
    ).toBeInTheDocument();

    expect(screen.getByRole('link', { name: 'Create an account' })).toHaveAttribute(
      'href',
      '/register',
    );
  });

  it('redirects an authenticated customer away from registration', async () => {
    vi.mocked(useSession).mockReturnValue(authenticated('customer'));

    open('/register');

    expect(
      await screen.findByRole('heading', {
        name: 'Customer Chat',
        level: 1,
      }),
    ).toBeInTheDocument();

    expect(
      screen.queryByRole('heading', {
        name: 'Create your account',
      }),
    ).not.toBeInTheDocument();
  });
});
