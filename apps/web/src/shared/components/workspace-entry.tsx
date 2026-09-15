// apps/web/src/shared/components/workspace-entry.tsx

import { useEffect, useRef } from 'react';
import { NavLink } from 'react-router';

import { useSession } from '../auth/session-context';
import { allowedWorkspaces, workspaceNames } from '../auth/workspace-access';
import type { Workspace } from '../auth/workspace-access';
import { identity } from '../branding/identity';

import './workspace-entry.css';

interface WorkspaceEntryProps {
  readonly workspace: Workspace;
  readonly description: string;
}

export function WorkspaceEntry({ workspace, description }: WorkspaceEntryProps) {
  const session = useSession();
  const heading = useRef<HTMLHeadingElement>(null);
  const title = workspaceNames[workspace];

  useEffect(() => {
    document.title = `${title} · ${identity.productName}`;
    heading.current?.focus();
  }, [title]);

  return (
    <div className="workspace-entry" data-workspace={workspace}>
      <a className="workspace-entry__skip" href="#workspace-content">
        Skip to content
      </a>

      <aside className="workspace-entry__rail">
        <div className="workspace-entry__brand">
          <svg width="32" height="32" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
            <path
              fill="currentColor"
              d="M24 2C27 17 31 21 46 24C31 27 27 31 24 46C21 31 17 27 2 24C17 21 21 17 24 2Z"
            />
          </svg>
          <span>{identity.productName}</span>
        </div>

        <nav aria-label="Workspaces">
          {allowedWorkspaces(session.user).map((item) => (
            <NavLink key={item} to={`/${item}`} className="workspace-entry__link" end>
              {workspaceNames[item]}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main
        id="workspace-content"
        className="workspace-entry__content"
        aria-labelledby="workspace-title"
        tabIndex={-1}
      >
        <header>
          <p className="workspace-entry__eyebrow">Workspace</p>
          <h1 id="workspace-title" ref={heading} tabIndex={-1}>
            {title}
          </h1>
          <p className="workspace-entry__description">{description}</p>
        </header>

        <section className="workspace-entry__panel" aria-labelledby="integration-title">
          <h2 id="integration-title">Workspace setup in progress</h2>
          <p>
            This workspace’s workflows are not connected yet. No records or metrics are displayed.
          </p>
        </section>
      </main>
    </div>
  );
}
