// apps/web/src/shared/auth/session-context.ts

import { createContext, useContext, useSyncExternalStore } from 'react';

import type { createSessionController } from './session-controller';
import type { SessionSnapshot } from './session-controller';

type SessionController = ReturnType<typeof createSessionController>;

export const SessionContext = createContext<SessionController | null>(null);

export function useSessionController(): SessionController {
  const controller = useContext(SessionContext);

  if (controller === null) {
    throw new Error('Session hooks require ApplicationProviders.');
  }

  return controller;
}

export function useSession(): SessionSnapshot {
  const controller = useSessionController();

  return useSyncExternalStore(controller.subscribe, controller.getSnapshot);
}
