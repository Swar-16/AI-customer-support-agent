// apps/web/src/features/chat/customer-escalation-query.ts
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import { useApiTransport } from '../../shared/api/transport-context';
import { useSession } from '../../shared/auth/session-context';
import { createCustomerEscalationApi } from './customer-escalation-api';

export function customerEscalationKey(customerId: string | null, conversationId: string) {
  return ['chat', customerId, 'conversation', conversationId, 'escalation-status'] as const;
}

export function useCustomerEscalation(conversationId: string, enabled: boolean) {
  const transport = useApiTransport();
  const session = useSession();

  const api = useMemo(() => createCustomerEscalationApi(transport), [transport]);

  const customerId =
    session.phase === 'authenticated' &&
    session.user?.role === 'customer' &&
    session.user.status === 'active'
      ? session.user.id
      : null;

  return useQuery({
    queryKey: customerEscalationKey(customerId, conversationId),
    enabled: enabled && customerId !== null,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: async ({ signal }) => {
      if (!enabled || customerId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      const result = await api.get(conversationId, signal);
      if (!result.ok) throw result.error;

      return result.data;
    },
  });
}
