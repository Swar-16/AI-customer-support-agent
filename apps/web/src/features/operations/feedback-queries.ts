// apps/web/src/features/operations/feedback-queries.ts
import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import { useApiTransport } from '../../shared/api/transport-context';
import { useSession } from '../../shared/auth/session-context';
import { createFeedbackApi, type FeedbackFilters } from './feedback-api';
import type { FeedbackReviewTargetStatus } from './feedback-contract';

export const feedbackKeys = {
  all: (operatorId: string | null) => ['operations', operatorId, 'feedback'] as const,

  lists: (operatorId: string | null) => [...feedbackKeys.all(operatorId), 'list'] as const,

  list: (operatorId: string | null, filters: FeedbackFilters) =>
    [
      ...feedbackKeys.lists(operatorId),
      {
        status: filters.status,
        rating: filters.rating,
        helpful: filters.helpful,
        reasonCode: filters.reasonCode,
        customerId: filters.customerId,
        conversationId: filters.conversationId,
        createdFrom: filters.createdFrom,
        createdTo: filters.createdTo,
        limit: filters.limit,
        offset: filters.offset,
      },
    ] as const,

  details: (operatorId: string | null) => [...feedbackKeys.all(operatorId), 'detail'] as const,

  detail: (operatorId: string | null, feedbackId: string | null) =>
    [...feedbackKeys.details(operatorId), feedbackId] as const,
};

function unwrap<T>(result: TransportResult<T>): T {
  if (!result.ok) {
    throw result.error;
  }

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

export function useFeedbackApi() {
  const transport = useApiTransport();

  return useMemo(() => createFeedbackApi(transport), [transport]);
}

export function useFeedbackList(filters: FeedbackFilters) {
  const api = useFeedbackApi();
  const operatorId = useOperatorId();

  return useQuery({
    queryKey: feedbackKeys.list(operatorId, filters),
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

export function useFeedbackDetail(feedbackId: string | null) {
  const api = useFeedbackApi();
  const operatorId = useOperatorId();

  return useQuery({
    queryKey: feedbackKeys.detail(operatorId, feedbackId),
    enabled: operatorId !== null && feedbackId !== null,
    retry: false,
    staleTime: 15_000,

    queryFn: async ({ signal }) => {
      if (operatorId === null || feedbackId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(await api.get(feedbackId, signal));
    },
  });
}

export interface ReviewFeedbackVariables {
  readonly feedbackId: string;
  readonly expectedRowVersion: number;
  readonly targetStatus: FeedbackReviewTargetStatus;
  readonly reviewNotes: string | null;
}

export function useReviewFeedback() {
  const api = useFeedbackApi();
  const operatorId = useOperatorId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ['operations', operatorId, 'feedback', 'review'],
    retry: false,

    mutationFn: async (variables: ReviewFeedbackVariables) => {
      if (operatorId === null) {
        throw SafeApiError.fromHttp(403, null);
      }

      return unwrap(
        await api.review(variables.feedbackId, {
          expected_row_version: variables.expectedRowVersion,
          target_status: variables.targetStatus,
          review_notes: variables.reviewNotes,
        }),
      );
    },

    onSuccess: async (_result, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: feedbackKeys.lists(operatorId),
        }),

        queryClient.invalidateQueries({
          queryKey: feedbackKeys.detail(operatorId, variables.feedbackId),
        }),
      ]);
    },
  });
}
