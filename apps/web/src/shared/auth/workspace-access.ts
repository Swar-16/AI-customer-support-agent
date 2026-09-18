// apps/web/src/shared/auth/workspace-access.ts

import type { AuthUser } from './auth-contract';

export type Workspace = 'chat' | 'operations' | 'knowledge';

export const workspaceNames: Record<Workspace, string> = {
  chat: 'Customer Chat',
  operations: 'Operations',
  knowledge: 'Knowledge',
};

const access = {
  customer: ['chat'],
  support_agent: ['operations'],
  admin: ['operations', 'knowledge'],
  system: [],
} satisfies Record<AuthUser['role'], readonly Workspace[]>;

export function allowedWorkspaces(user: Readonly<AuthUser> | null): readonly Workspace[] {
  if (
    user === null ||
    user.status !== 'active' ||
    !Object.prototype.hasOwnProperty.call(access, user.role)
  ) {
    return [];
  }

  return access[user.role];
}

export function canOpenWorkspace(user: Readonly<AuthUser> | null, workspace: Workspace): boolean {
  return allowedWorkspaces(user).includes(workspace);
}

export function homePath(user: Readonly<AuthUser> | null): string | null {
  const workspace = allowedWorkspaces(user)[0];
  return workspace === undefined ? null : `/${workspace}`;
}
