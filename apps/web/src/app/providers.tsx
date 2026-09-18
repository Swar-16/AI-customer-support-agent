// apps/web/src/app/providers.tsx

import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { SessionContext } from '../shared/auth/session-context';
import type { ApplicationRuntime } from './runtime';
import { TransportContext } from '../shared/api/transport-context';

interface ApplicationProvidersProps {
  readonly runtime: ApplicationRuntime;
  readonly children: ReactNode;
}

export function ApplicationProviders({ runtime, children }: ApplicationProvidersProps) {
  return (
    <QueryClientProvider client={runtime.queryClient}>
      <SessionContext.Provider value={runtime.session}>
        <TransportContext.Provider value={runtime.request}>{children}</TransportContext.Provider>
      </SessionContext.Provider>
    </QueryClientProvider>
  );
}
