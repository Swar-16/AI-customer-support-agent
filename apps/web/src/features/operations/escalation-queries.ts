// apps/web/src/features/operations/escalation-queries.ts
import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import { useApiTransport } from '../../shared/api/transport-context';
import { useSession } from '../../shared/auth/session-context';
import { createEscalationApi, type EscalationFilters } from './escalation-api';
import { createEscalationTicketApi } from './escalation-ticket-api';
import type { EscalationStatus, EscalationTicketDraft } from './escalation-contract';

export const escalationKeys = {
  all: (operatorId: string | null) => ['operations', operatorId, 'escalations'] as const,

  lists: (operatorId: string | null) => [...escalationKeys.all(operatorId), 'list'] as const,

  list: (operatorId: string | null, filters: EscalationFilters) =>
    [
      ...escalationKeys.lists(operatorId),
      {
        activeOnly: filters.activeOnly,
        status: filters.status,
        priority: filters.priority,
        reasonCode: filters.reasonCode,
        limit: filters.limit,
        offset: filters.offset,
      },
    ] as const,

  details: (operatorId: string | null) => [...escalationKeys.all(operatorId), 'detail'] as const,

  detail: (operatorId: string | null, escalationId: string | null) =>
    [...escalationKeys.details(operatorId), escalationId] as const,
};

function unwrap<T>(result: TransportResult<T>): T {
  if (!result.ok) throw result.error;
  return result.data;
}

function useOperatorId(): string | null {
  const session = useSession();

  if (session.phase !== 'authenticated' || session.user?.status !== 'active') {
    return null;
  }

  return session.user.role === 'admin' || session.user.role === 'support_agent'
    ? session.user.id
    : null;
}

export function useEscalationApi() {
  const transport = useApiTransport();

  return useMemo(() => createEscalationApi(transport), [transport]);
}

export function useEscalationTicketApi() {
  const transport = useApiTransport();

  return useMemo(() => createEscalationTicketApi(transport), [transport]);
}

export function useEscalationList(filters: EscalationFilters) {
  const api = useEscalationApi();
  const operatorId = useOperatorId();

  return useQuery({
    queryKey: escalationKeys.list(operatorId, filters),
    enabled: operatorId !== null,
    retry: false,
    staleTime: 15_000,
    queryFn: async ({ signal }) => {
      if (operatorId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.list(filters, signal));
    },
  });
}

export function useEscalationDetail(escalationId: string | null) {
  const api = useEscalationApi();
  const operatorId = useOperatorId();

  return useQuery({
    queryKey: escalationKeys.detail(operatorId, escalationId),
    enabled: operatorId !== null && escalationId !== null,
    retry: false,
    staleTime: 15_000,
    queryFn: async ({ signal }) => {
      if (operatorId === null || escalationId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.get(escalationId, signal));
    },
  });
}

interface UpdateEscalationVariables {
  readonly escalationId: string;
  readonly status: EscalationStatus;
  readonly customerMessage: string | null;
}

export function useUpdateEscalationStatus() {
  const api = useEscalationApi();
  const operatorId = useOperatorId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ['operations', operatorId, 'escalations', 'update-status'],
    retry: false,

    mutationFn: async ({ escalationId, status, customerMessage }: UpdateEscalationVariables) => {
      if (operatorId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      const terminal = status === 'resolved' || status === 'dismissed';

      return unwrap(
        await api.updateStatus(
          escalationId,
          terminal
            ? {
                status,
                customer_message: customerMessage,
              }
            : {
                status,
              },
        ),
      );
    },

    onSettled: async (_result, _error, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: escalationKeys.lists(operatorId),
        }),

        queryClient.invalidateQueries({
          queryKey: escalationKeys.detail(
            operatorId,
            variables.escalationId,
          ),
        }),

        /*
        * Escalation transitions can persist a customer-visible
        * conversation notice.
        */
        queryClient.invalidateQueries({
          queryKey: ['chat'],
        }),
      ]);
    },
  });
}

interface CreateEscalationTicketVariables {
  readonly escalationId: string;
  readonly draft: EscalationTicketDraft;
}

export function useCreateEscalationTicket() {
  const api = useEscalationTicketApi();
  const operatorId = useOperatorId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ['operations', operatorId, 'escalations', 'create-ticket'],
    retry: false,

    mutationFn: async ({ escalationId, draft }: CreateEscalationTicketVariables) => {
      if (operatorId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.create(escalationId, draft));
    },

    onSuccess: async () => {
      await Promise.all([
        /*
         * Covers escalation detail/list, ticket detail/list, and Operations
         * analytics. The backend may return an existing linked ticket during an
         * idempotent retry.
         */
        queryClient.invalidateQueries({
          queryKey: ['operations', operatorId],
        }),

        /*
         * Refresh the customer-visible ticket-created notice and linked-ticket
         * escalation status.
         */
        queryClient.invalidateQueries({
          queryKey: ['chat'],
        }),
      ]);
    },
  });
}
