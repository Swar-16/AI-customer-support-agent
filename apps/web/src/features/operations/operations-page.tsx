// apps/web/src/features/operations/operations-page.tsx
import { useEffect } from 'react';
import { Navigate, NavLink, useLocation } from 'react-router';
import {
  Activity,
  BookOpenCheck,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  ShieldAlert,
  Sparkles,
  Star,
  TicketCheck,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { identity } from '../../shared/branding/identity';
import { useSession } from '../../shared/auth/session-context';
import { useLogoutDialog } from '../auth/logout-dialog-context';
import { AIActivityPage } from './ai-activity-page';
import { OperationsOverview } from './operations-overview';
import { OperationsConversationQueue } from './operations-conversation-queue';
import { EscalationQueue } from './escalation-queue';
import { TicketQueue } from './ticket-queue';
import { FeedbackQueue } from './feedback-queue';
import { KnowledgeHealthPage } from './knowledge-health-page';

import './operations-page.css';

type OperationsRole = 'admin' | 'support_agent';

interface NavigationItem {
  readonly key: string;
  readonly label: string;
  readonly description: string;
  readonly icon: LucideIcon;
  readonly roles: readonly OperationsRole[];
}

const navigation = [
  {
    key: 'overview',
    label: 'Overview',
    description: 'Operational health and current priorities.',
    icon: LayoutDashboard,
    roles: ['admin'],
  },
  {
    key: 'conversations',
    label: 'Conversations',
    description: 'Inspect authorized customer conversations.',
    icon: MessageSquareText,
    roles: ['admin'],
  },
  {
    key: 'escalations',
    label: 'Escalations',
    description: 'Review and coordinate human-support requests.',
    icon: ShieldAlert,
    roles: ['admin', 'support_agent'],
  },
  {
    key: 'tickets',
    label: 'Tickets',
    description: 'Triage, assign, and resolve support tickets.',
    icon: TicketCheck,
    roles: ['admin', 'support_agent'],
  },
  {
    key: 'feedback',
    label: 'Feedback',
    description: 'Review customer feedback and response quality.',
    icon: Star,
    roles: ['admin', 'support_agent'],
  },
  {
    key: 'ai-activity',
    label: 'AI activity',
    description: 'Inspect AI runs, retrieval, and provider activity.',
    icon: Activity,
    roles: ['admin'],
  },
  {
    key: 'knowledge-health',
    label: 'Knowledge health',
    description: 'Monitor document readiness and ingestion failures.',
    icon: BookOpenCheck,
    roles: ['admin'],
  },
] satisfies readonly NavigationItem[];

function PlannedSection({ item }: { readonly item: NavigationItem }) {
  const Icon = item.icon;

  return (
    <section className="operations-planned">
      <span className="operations-planned__icon">
        <Icon size={26} aria-hidden="true" />
      </span>

      <p className="operations-kicker">Next implementation slice</p>
      <h2>{item.label}</h2>
      <p>{item.description}</p>
    </section>
  );
}

export default function OperationsPage() {
  const session = useSession();
  const location = useLocation();
  const requestLogout = useLogoutDialog();

  const user = session.phase === 'authenticated' ? session.user : null;

  const role: OperationsRole | null =
    user?.role === 'admin' || user?.role === 'support_agent' ? user.role : null;

  const allowedNavigation =
    role === null ? [] : navigation.filter((item) => item.roles.includes(role));

  const defaultPath = role === 'support_agent' ? '/operations/escalations' : '/operations/overview';

  const sectionKey = location.pathname.replace(/^\/operations\/?/u, '').split('/')[0] ?? '';

  const activeItem = allowedNavigation.find((item) => item.key === sectionKey);

  /*
   * This hook must run before every possible early return. Calling it after
   * redirects or authentication checks violates React's hook-order rules.
   */
  useEffect(() => {
    const pageName = activeItem?.label ?? 'Operations';
    document.title = `${pageName} · ${identity.productName}`;
  }, [activeItem?.label]);

  if (user === null) {
    return null;
  }

  if (role === null) {
    return <Navigate replace to="/" />;
  }

  if (sectionKey.length === 0) {
    return <Navigate replace to={defaultPath} />;
  }

  if (activeItem === undefined) {
    return <Navigate replace to={defaultPath} />;
  }

  const displayName = user.display_name?.trim() || user.email.trim();

  const displayInitial = displayName.charAt(0).toUpperCase() || 'U';

  return (
    <div className="operations-workspace">
      <a className="operations-skip" href="#operations-content">
        Skip to operations content
      </a>

      <aside className="operations-rail">
        <NavLink className="operations-brand" to={defaultPath}>
          <span className="operations-brand__mark" aria-hidden="true">
            <Sparkles size={20} />
          </span>
          <span>{identity.productName}</span>
        </NavLink>

        <div className="operations-rail__heading">
          <small>Workspace</small>
          <strong>Operations</strong>
        </div>

        <nav aria-label="Operations navigation">
          {allowedNavigation.map((item) => {
            const Icon = item.icon;

            return (
              <NavLink
                className={({ isActive }) => `operations-nav-link${isActive ? ' is-active' : ''}`}
                key={item.key}
                to={`/operations/${item.key}`}
              >
                <Icon size={19} aria-hidden="true" />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div className="operations-account">
          <div className="operations-account__identity">
            <span aria-hidden="true">{displayInitial}</span>

            <div>
              <strong>{displayName}</strong>
              <small>{role === 'admin' ? 'Administrator' : 'Support agent'}</small>
            </div>
          </div>

          <button
            type="button"
            className="operations-signout"
            aria-label="Sign out"
            title="Sign out"
            onClick={requestLogout}
          >
            <LogOut size={19} aria-hidden="true" />
          </button>
        </div>
      </aside>

      <main className="operations-main" id="operations-content">
        <header className="operations-header">
          <div>
            <p className="operations-kicker">Operations workspace</p>
            <h1>{activeItem.label}</h1>
            <p>{activeItem.description}</p>
          </div>
        </header>

        {activeItem.key === 'overview' ? (
          <OperationsOverview />
        ) : activeItem.key === 'conversations' ? (
          <OperationsConversationQueue />
        ) : activeItem.key === 'escalations' ? (
          <EscalationQueue />
        ) : activeItem.key === 'tickets' ? (
          <TicketQueue />
        ) : activeItem.key === 'feedback' ? (
          <FeedbackQueue />
        ) : activeItem.key === 'ai-activity' ? (
          <AIActivityPage />
        ) : activeItem.key === 'knowledge-health' ? (
          <KnowledgeHealthPage />
        ) : (
          <PlannedSection item={activeItem} />
        )}
      </main>
    </div>
  );
}
