// apps/web/src/features/chat/chat-navigation-guard.tsx
import { useCallback, useContext, useEffect, useSyncExternalStore } from 'react';
import { useBlocker } from 'react-router';
import type { BlockerFunction } from 'react-router';

import { useSession, useSessionController } from '../../shared/auth/session-context';
import { NavigationProtectionContext } from '../../shared/navigation/navigation-protection';
import { DraftExitDialog } from './draft-exit-dialog';

interface ChatLocation {
  readonly pathname: string;
  readonly search: string;
}

function editorIdentity(location: ChatLocation): string {
  const pathname = location.pathname.replace(/\/+$/u, '') || '/';

  if (pathname === '/chat') {
    const isDraft = new URLSearchParams(location.search).get('draft') === '1';

    return isDraft ? '/chat:draft' : '/chat:welcome';
  }

  // Pagination and other query changes do not change the active editor.
  return pathname;
}

export function ChatNavigationGuard() {
  const protection = useContext(NavigationProtectionContext);
  const session = useSession();
  const controller = useSessionController();

  if (protection === null) {
    throw new Error('NavigationProtectionProvider is required.');
  }

  const protectedEditor = useSyncExternalStore(
    protection.subscribe,
    protection.getSnapshot,
    protection.getSnapshot,
  );

  const shouldBlock = useCallback<BlockerFunction>(
    ({ currentLocation, nextLocation }) => {
      // Read the current session at navigation time, including immediately
      // after logout or session invalidation.
      if (controller.getSnapshot().phase !== 'authenticated') {
        return false;
      }

      if (!protection.getSnapshot()) {
        return false;
      }

      return editorIdentity(currentLocation) !== editorIdentity(nextLocation);
    },
    [controller, protection],
  );

  const blocker = useBlocker(shouldBlock);
  const authenticated = session.phase === 'authenticated';

  useEffect(() => {
    if (blocker.state === 'blocked' && (!authenticated || !protectedEditor)) {
      // Cancel the old blocked destination when protection disappears.
      // Authentication redirects can then follow their normal route.
      blocker.reset();
    }
  }, [authenticated, blocker, protectedEditor]);

  if (blocker.state !== 'blocked' || !authenticated || !protectedEditor) {
    return null;
  }

  return (
    <DraftExitDialog
      startingNew={false}
      onCancel={() => {
        if (blocker.state === 'blocked') {
          blocker.reset();
        }
      }}
      onConfirm={() => {
        if (blocker.state === 'blocked') {
          blocker.proceed();
        }
      }}
    />
  );
}
