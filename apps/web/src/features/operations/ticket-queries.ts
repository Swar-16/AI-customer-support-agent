// apps/web/src/features/operations/ticket-queries.ts
import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import { useApiTransport } from '../../shared/api/transport-context';
import { useSession } from '../../shared/auth/session-context';
import {
  createTicketApi,
  type AddTicketCommentInput,
  type TicketFilters,
  type TicketUpdateInput,
} from './ticket-api';

export const ticketKeys = {
  all: (operatorId: string | null) => ['operations', operatorId, 'tickets'] as const,

  lists: (operatorId: string | null) => [...ticketKeys.all(operatorId), 'list'] as const,

  list: (operatorId: string | null, filters: TicketFilters) =>
    [
      ...ticketKeys.lists(operatorId),
      {
        activeOnly: filters.activeOnly,
        status: filters.status,
        priority: filters.priority,
        category: filters.category,
        assignedAgentId: filters.assignedAgentId,
        unassignedOnly: filters.unassignedOnly,
        limit: filters.limit,
        offset: filters.offset,
      },
    ] as const,

  details: (operatorId: string | null) => [...ticketKeys.all(operatorId), 'detail'] as const,

  detail: (operatorId: string | null, ticketId: string | null) =>
    [...ticketKeys.details(operatorId), ticketId] as const,
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

export function useTicketApi() {
  const transport = useApiTransport();

  return useMemo(() => createTicketApi(transport), [transport]);
}

export function useTicketList(filters: TicketFilters) {
  const api = useTicketApi();
  const operatorId = useOperatorId();

  return useQuery({
    queryKey: ticketKeys.list(operatorId, filters),
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

export function useTicketDetail(ticketId: string | null) {
  const api = useTicketApi();
  const operatorId = useOperatorId();

  return useQuery({
    queryKey: ticketKeys.detail(operatorId, ticketId),
    enabled: operatorId !== null && ticketId !== null,
    retry: false,
    staleTime: 15_000,
    queryFn: async ({ signal }) => {
      if (operatorId === null || ticketId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.get(ticketId, signal));
    },
  });
}

interface UpdateTicketVariables {
  readonly ticketId: string;
  readonly update: TicketUpdateInput;
}

export function useUpdateTicket() {
  const api = useTicketApi();
  const operatorId = useOperatorId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ['operations', operatorId, 'tickets', 'update'],
    retry: false,

    mutationFn: async ({ ticketId, update }: UpdateTicketVariables) => {
      if (operatorId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.update(ticketId, update));
    },

    onSuccess: async (_result, variables) => {
      const refreshConversation =
        variables.update.targetStatus !== null && variables.update.targetStatus !== undefined;

      await Promise.all([
        /* Refreshes ticket detail/list, linked escalation state, and Operations analytics. */
        queryClient.invalidateQueries({
          queryKey: ['operations', operatorId],
        }),

        /*
         * Only status transitions create lifecycle conversation messages.
         * Priority, category, and assignment-only changes should not cause unnecessary chat refreshes.
         */
        ...(refreshConversation
          ? [
              queryClient.invalidateQueries({
                queryKey: ['chat'],
              }),
            ]
          : []),
      ]);
    },

    onError: async (error, variables) => {
      if (error instanceof SafeApiError && error.status === 409) {
        await queryClient.invalidateQueries({
          queryKey: ticketKeys.detail(operatorId, variables.ticketId),
        });
      }
    },
  });
}

interface AddCommentVariables {
  readonly ticketId: string;
  readonly comment: AddTicketCommentInput;
}

export function useAddTicketComment() {
  const api = useTicketApi();
  const operatorId = useOperatorId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ['operations', operatorId, 'tickets', 'comment'],
    retry: false,

    mutationFn: async ({ ticketId, comment }: AddCommentVariables) => {
      if (operatorId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.addComment(ticketId, comment));
    },

    onSuccess: async (_result, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ticketKeys.detail(operatorId, variables.ticketId),
        }),

        /*
         * Comments can affect operational activity and analytics, but they are
         * not fabricated as customer chat lifecycle messages.
         */
        queryClient.invalidateQueries({
          queryKey: ['operations', operatorId],
        }),
      ]);
    },
  });
}
