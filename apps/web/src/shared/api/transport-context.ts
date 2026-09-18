// apps/web/src/shared/api/transport-context.ts

import { createContext, useContext } from 'react';

import type { createTransport } from './transport';

export type ApiTransport = ReturnType<typeof createTransport>;

export const TransportContext = createContext<ApiTransport | null>(null);

export function useApiTransport(): ApiTransport {
  const transport = useContext(TransportContext);

  if (transport === null) {
    throw new Error('API hooks require ApplicationProviders.');
  }

  return transport;
}
