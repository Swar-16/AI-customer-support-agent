// apps/web/src/features/operations/operations-authorization.test.tsx
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuthUser } from '../../shared/auth/auth-contract';
import { useSession } from '../../shared/auth/session-context';
import type { SessionSnapshot } from '../../shared/auth/session-controller';
import OperationsPage from './operations-page';

vi.mock('../../shared/auth/session-context', () => ({
  useSession: vi.fn(),
}));

const requestLogout = vi.fn();

vi.mock('../auth/logout-dialog-context', () => ({
  useLogoutDialog: () => requestLogout,
}));

vi.mock('./operations-overview', () => ({
  OperationsOverview: () => <section data-testid="overview-screen">Overview content</section>,
}));

vi.mock('./operations-conversation-queue', () => ({
  OperationsConversationQueue: () => (
    <section data-testid="conversations-screen">Conversations content</section>
  ),
}));

vi.mock('./escalation-queue', () => ({
  EscalationQueue: () => <section data-testid="escalations-screen">Escalations content</section>,
}));

vi.mock('./ticket-queue', () => ({
  TicketQueue: () => <section data-testid="tickets-screen">Tickets content</section>,
}));

vi.mock('./feedback-queue', () => ({
  FeedbackQueue: () => <section data-testid="feedback-screen">Feedback content</section>,
}));

vi.mock('./ai-activity-page', () => ({
  AIActivityPage: () => <section data-testid="ai-activity-screen">AI activity content</section>,
}));

vi.mock('./knowledge-health-page', () => ({
  KnowledgeHealthPage: () => (
    <section data-testid="knowledge-health-screen">Knowledge health content</section>
  ),
}));

function authenticated(role: AuthUser['role']): SessionSnapshot {
  return {
    phase: 'authenticated',
    error: null,
    user: {
      id: 'd44e99cb-8e10-4af8-9bb7-c4d293042943',
      email: `${role}@example.test`,
      display_name: `${role} user`,
      role,
      status: 'active',
      created_at: '2026-09-15T10:00:00Z',
    },
  };
}

function openOperations(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/operations/*" element={<OperationsPage />} />

        <Route path="/" element={<div data-testid="customer-workspace">Customer workspace</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();

  vi.mocked(useSession).mockReturnValue(authenticated('admin'));
});

describe('Operations authorization matrix', () => {
  it('shows every Operations destination to administrators', () => {
    openOperations('/operations/overview');

    const navigation = screen.getByRole('navigation', {
      name: 'Operations navigation',
    });

    for (const name of [
      'Overview',
      'Conversations',
      'Escalations',
      'Tickets',
      'Feedback',
      'AI activity',
      'Knowledge health',
    ]) {
      expect(
        within(navigation).getByRole('link', {
          name,
        }),
      ).toBeInTheDocument();
    }
  });

  it.each([
    ['/operations/overview', 'Overview', 'overview-screen'],
    ['/operations/conversations', 'Conversations', 'conversations-screen'],
    ['/operations/escalations', 'Escalations', 'escalations-screen'],
    ['/operations/tickets', 'Tickets', 'tickets-screen'],
    ['/operations/feedback', 'Feedback', 'feedback-screen'],
    ['/operations/ai-activity', 'AI activity', 'ai-activity-screen'],
    ['/operations/knowledge-health', 'Knowledge health', 'knowledge-health-screen'],
  ] as const)('allows an administrator to open %s', (path, heading, testId) => {
    vi.mocked(useSession).mockReturnValue(authenticated('admin'));

    openOperations(path);

    expect(
      screen.getByRole('heading', {
        name: heading,
        level: 1,
      }),
    ).toBeInTheDocument();

    expect(screen.getByTestId(testId)).toBeInTheDocument();
  });

  it('shows only agent-authorized destinations to support agents', () => {
    vi.mocked(useSession).mockReturnValue(authenticated('support_agent'));

    openOperations('/operations/escalations');

    const navigation = screen.getByRole('navigation', {
      name: 'Operations navigation',
    });

    for (const name of ['Escalations', 'Tickets', 'Feedback']) {
      expect(
        within(navigation).getByRole('link', {
          name,
        }),
      ).toBeInTheDocument();
    }

    for (const name of ['Overview', 'Conversations', 'AI activity', 'Knowledge health']) {
      expect(
        within(navigation).queryByRole('link', {
          name,
        }),
      ).not.toBeInTheDocument();
    }
  });

  it.each([
    ['/operations/escalations', 'Escalations', 'escalations-screen'],
    ['/operations/tickets', 'Tickets', 'tickets-screen'],
    ['/operations/feedback', 'Feedback', 'feedback-screen'],
  ] as const)('allows a support agent to open %s', (path, heading, testId) => {
    vi.mocked(useSession).mockReturnValue(authenticated('support_agent'));

    openOperations(path);

    expect(
      screen.getByRole('heading', {
        name: heading,
        level: 1,
      }),
    ).toBeInTheDocument();

    expect(screen.getByTestId(testId)).toBeInTheDocument();
  });

  it.each([
    '/operations/overview',
    '/operations/conversations',
    '/operations/ai-activity',
    '/operations/knowledge-health',
  ])('redirects a support agent away from %s', (path) => {
    vi.mocked(useSession).mockReturnValue(authenticated('support_agent'));

    openOperations(path);

    expect(
      screen.getByRole('heading', {
        name: 'Escalations',
        level: 1,
      }),
    ).toBeInTheDocument();

    expect(screen.getByTestId('escalations-screen')).toBeInTheDocument();
  });

  it('redirects customers out of Operations', () => {
    vi.mocked(useSession).mockReturnValue(authenticated('customer'));

    openOperations('/operations/tickets');

    expect(screen.getByTestId('customer-workspace')).toBeInTheDocument();

    expect(
      screen.queryByRole('navigation', {
        name: 'Operations navigation',
      }),
    ).not.toBeInTheDocument();
  });

  it('redirects system accounts out of Operations', () => {
    vi.mocked(useSession).mockReturnValue(authenticated('system'));

    openOperations('/operations/overview');

    expect(screen.getByTestId('customer-workspace')).toBeInTheDocument();

    expect(
      screen.queryByRole('navigation', {
        name: 'Operations navigation',
      }),
    ).not.toBeInTheDocument();
  });

  it('uses escalations as the support-agent default', () => {
    vi.mocked(useSession).mockReturnValue(authenticated('support_agent'));

    openOperations('/operations');

    expect(
      screen.getByRole('heading', {
        name: 'Escalations',
        level: 1,
      }),
    ).toBeInTheDocument();
  });

  it('uses overview as the administrator default', () => {
    vi.mocked(useSession).mockReturnValue(authenticated('admin'));

    openOperations('/operations');

    expect(
      screen.getByRole('heading', {
        name: 'Overview',
        level: 1,
      }),
    ).toBeInTheDocument();
  });
});
