// apps/web/src/features/knowledge/knowledge-page.tsx

import { useEffect } from 'react';
import { Navigate, NavLink, Outlet, useLocation } from 'react-router';
import { Activity, BookOpenText, Library, LogOut, PanelsTopLeft, Sparkles } from 'lucide-react';

import { useSession } from '../../shared/auth/session-context';
import { identity } from '../../shared/branding/identity';
import { useLogoutDialog } from '../auth/logout-dialog-context';

import './knowledge-page.css';

interface KnowledgePageIdentity {
  readonly eyebrow: string;
  readonly title: string;
  readonly description: string;
}

function getKnowledgePageIdentity(pathname: string): KnowledgePageIdentity {
  if (/^\/knowledge\/documents\/[^/]+\/versions\/[^/]+\/?$/u.test(pathname)) {
    return {
      eyebrow: 'Version inspection',
      title: 'Version details',
      description: 'Inspect source metadata, ingestion progress, and lifecycle state.',
    };
  }

  if (/^\/knowledge\/documents\/[^/]+\/?$/u.test(pathname)) {
    return {
      eyebrow: 'Document workspace',
      title: 'Document details',
      description: 'Manage immutable versions and the document publication lifecycle.',
    };
  }

  return {
    eyebrow: 'Knowledge workspace',
    title: 'Document library',
    description: 'Shape the source material your support AI can trust.',
  };
}

export default function KnowledgePage() {
  const session = useSession();
  const location = useLocation();
  const requestLogout = useLogoutDialog();

  const pageIdentity = getKnowledgePageIdentity(location.pathname);

  /*
   * Keep this hook before every possible early return so
   * React's hook order remains stable.
   */
  useEffect(() => {
    document.title = `${pageIdentity.title} · ${identity.productName}`;
  }, [pageIdentity.title]);

  const user = session.phase === 'authenticated' ? session.user : null;

  if (user === null) {
    return null;
  }

  /*
   * RequireWorkspace remains the primary authorization
   * boundary. This is a defensive guard in case the page is
   * ever mounted outside that protected route.
   */
  if (user.role !== 'admin' || user.status !== 'active') {
    return <Navigate replace to="/" />;
  }

  const displayName = user.display_name?.trim() || user.email.trim();

  const displayInitial = displayName.charAt(0).toUpperCase() || 'A';

  return (
    <div className="knowledge-workspace">
      <a className="knowledge-skip" href="#knowledge-content">
        Skip to knowledge content
      </a>

      <aside className="knowledge-rail">
        <NavLink
          className="knowledge-brand"
          to="/knowledge"
          end
          aria-label={`${identity.productName} Knowledge Studio`}
        >
          <span className="knowledge-brand__mark" aria-hidden="true">
            <BookOpenText size={20} />

            <Sparkles className="knowledge-brand__spark" size={11} />
          </span>

          <span>{identity.productName}</span>
        </NavLink>

        <div className="knowledge-rail__heading">
          <small>Workspace</small>
          <strong>Knowledge Studio</strong>
        </div>

        <nav aria-label="Knowledge Studio navigation">
          <NavLink
            className={({ isActive }) =>
              ['knowledge-nav-link', isActive ? 'is-active' : ''].filter(Boolean).join(' ')
            }
            to="/knowledge"
            end
          >
            <Library size={19} aria-hidden="true" />

            <span>Document library</span>
          </NavLink>
        </nav>

        <div className="knowledge-rail__workspace-links">
          <p>Switch workspace</p>

          <NavLink className="knowledge-workspace-link" to="/operations/overview">
            <PanelsTopLeft size={18} aria-hidden="true" />

            <span>
              <strong>Operations</strong>
              <small>Support command center</small>
            </span>
          </NavLink>

          <NavLink className="knowledge-workspace-link" to="/operations/knowledge-health">
            <Activity size={18} aria-hidden="true" />

            <span>
              <strong>Knowledge health</strong>
              <small>Readiness and ingestion signals</small>
            </span>
          </NavLink>
        </div>

        <div className="knowledge-account">
          <div className="knowledge-account__identity">
            <span aria-hidden="true">{displayInitial}</span>

            <div>
              <strong>{displayName}</strong>
              <small>Administrator</small>
            </div>
          </div>

          <button
            type="button"
            className="knowledge-signout"
            aria-label="Sign out"
            title="Sign out"
            onClick={requestLogout}
          >
            <LogOut size={19} aria-hidden="true" />
          </button>
        </div>
      </aside>

      <main className="knowledge-main" id="knowledge-content">
        <header className="knowledge-header">
          <div className="knowledge-header__copy">
            <p className="knowledge-kicker">{pageIdentity.eyebrow}</p>

            <h1>{pageIdentity.title}</h1>

            <p>{pageIdentity.description}</p>
          </div>

          <div className="knowledge-header__identity" aria-label="Current workspace">
            <span aria-hidden="true">
              <BookOpenText size={18} />
            </span>

            <div>
              <small>Knowledge Studio</small>
              <strong>Admin workspace</strong>
            </div>
          </div>
        </header>

        <div className="knowledge-content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
