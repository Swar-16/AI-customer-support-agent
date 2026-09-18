// apps/web/src/features/chat/response-feedback-target.ts
import { skipToken, useQuery, type QueryClient } from '@tanstack/react-query';

import { useSession } from '../../shared/auth/session-context';
import type { SendMessageResult } from './chat-contract';

export interface ResponseFeedbackTarget {
  readonly conversationId: string;
  readonly responseMessageId: string;
  readonly aiRunId: string;
}

export function responseFeedbackTargetKey(
  customerId: string | null,
  conversationId: string,
  responseMessageId: string,
) {
  return [
    'chat',
    customerId,
    'conversation',
    conversationId,
    'feedback-target',
    responseMessageId,
  ] as const;
}

/**
 * Call only with an API-decoded response after confirming that the
 * authenticated session still matches the session that submitted it.
 */
export function rememberResponseFeedbackTarget(
  queryClient: QueryClient,
  customerId: string,
  conversationId: string,
  result: SendMessageResult,
): void {
  if (
    !result.succeeded ||
    result.conversation_id !== conversationId ||
    !result.assistant_message_id ||
    !result.ai_run_id ||
    !result.response?.trim()
  ) {
    return;
  }

  const target: ResponseFeedbackTarget = {
    conversationId,
    responseMessageId: result.assistant_message_id,
    aiRunId: result.ai_run_id,
  };

  queryClient.setQueryData<ResponseFeedbackTarget>(
    responseFeedbackTargetKey(customerId, conversationId, target.responseMessageId),
    target,
  );
}

export function useResponseFeedbackTarget(
  conversationId: string,
  responseMessageId: string,
): ResponseFeedbackTarget | undefined {
  const session = useSession();

  const customerId =
    session.phase === 'authenticated' &&
    session.user?.role === 'customer' &&
    session.user.status === 'active'
      ? session.user.id
      : null;

  const query = useQuery<ResponseFeedbackTarget>({
    queryKey: responseFeedbackTargetKey(customerId, conversationId, responseMessageId),
    queryFn: skipToken,
    staleTime: Infinity,
    gcTime: 5 * 60 * 1000,
  });

  return customerId === null ? undefined : query.data;
}
