// apps/web/src/features/auth/login-destination.ts

import type { AuthUser } from '../../shared/auth/auth-contract';
import { allowedWorkspaces, homePath } from '../../shared/auth/workspace-access';

export function loginDestination(state: unknown, user: Readonly<AuthUser> | null): string | null {
  const fallback = homePath(user);

  if (typeof state !== 'object' || state === null || Array.isArray(state)) {
    return fallback;
  }

  const candidate = (state as Record<string, unknown>).returnTo;

  if (typeof candidate !== 'string') {
    return fallback;
  }

  const permitted = allowedWorkspaces(user).some((workspace) => candidate === `/${workspace}`);

  return permitted ? candidate : fallback;
}
