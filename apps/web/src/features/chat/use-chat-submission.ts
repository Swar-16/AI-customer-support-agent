// apps/web/src/features/chat/use-chat-submission.ts
import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import { useSession, useSessionController } from '../../shared/auth/session-context';
import type { SendMessageResult } from './chat-contract';
import { chatKeys, useChatApi } from './chat-queries';
import { customerEscalationKey } from './customer-escalation-query';
import { rememberResponseFeedbackTarget } from './response-feedback-target';
import type { OutgoingMessage } from './outgoing-message';

interface ChatSubmissionOptions {
  readonly conversationId: string;
  readonly onPageChange: (offset: number) => void;
}

function unwrap<T>(result: TransportResult<T>): T {
  if (!result.ok) throw result.error;
  return result.data;
}

export function useChatSubmission({ conversationId, onPageChange }: ChatSubmissionOptions) {
  const api = useChatApi();
  const queryClient = useQueryClient();
  const session = useSession();
  const controller = useSessionController();
  const mounted = useRef(false);
  const [outgoing, setOutgoing] = useState<OutgoingMessage | null>(null);
  const outgoingRef = useRef<OutgoingMessage | null>(null);
  const attemptRef = useRef(0);
  const sendingRef = useRef(false);

  const publishOutgoing = useCallback((next: OutgoingMessage | null) => {
    outgoingRef.current = next;
    if (mounted.current) setOutgoing(next);
  }, []);

  function updateOutgoing(localId: string, patch: Partial<OutgoingMessage>) {
    const current = outgoingRef.current;
    if (current?.localId === localId) publishOutgoing({ ...current, ...patch });
  }

  function clearOutgoing() {
    if (!sendingRef.current) publishOutgoing(null);
  }

  useEffect(() => {
    return controller.subscribe(() => {
      if (controller.getSnapshot() !== session) publishOutgoing(null);
    });
  }, [controller, session, publishOutgoing]);

  useEffect(() => {
    mounted.current = true;

    return () => {
      mounted.current = false;
      outgoingRef.current = null;
    };
  }, []);

  function requireCurrentSession() {
    if (
      controller.getSnapshot() !== session ||
      session.phase !== 'authenticated' ||
      session.user?.role !== 'customer' ||
      session.user.status !== 'active'
    ) {
      throw SafeApiError.fromLocal('aborted');
    }

    return session.user.id;
  }

  const mutation = useMutation({
    retry: false,

    // Attempt immediately; do not queue a message for a later reconnect.
    networkMode: 'always',

    // Remove inactive mutation data promptly, including submitted text.
    gcTime: 0,

    mutationFn: async (message: string): Promise<TransportResult<SendMessageResult>> => {
      const customerId = requireCurrentSession();

      const result = await api.send(conversationId, message);

      // A response from a previous session must never repopulate the cache.
      requireCurrentSession();

      if (result.ok) {
        rememberResponseFeedbackTarget(queryClient, customerId, conversationId, result.data);
      }

      return result;
    },
  });

  async function send(message: string): Promise<TransportResult<SendMessageResult>> {
    requireCurrentSession();
    if (!mounted.current || sendingRef.current) throw SafeApiError.fromLocal('aborted');

    sendingRef.current = true;
    const localId = `${conversationId}:${++attemptRef.current}`;
    publishOutgoing({
      localId,
      content: message,
      createdAt: new Date().toISOString(),
      messageId: null,
      phase: 'sending',
    });

    try {
      const result = await mutation.mutateAsync(message);
      requireCurrentSession();
      if (result.ok) {
        updateOutgoing(localId, {
          messageId: result.data.customer_message_id,
          phase: 'syncing',
        });
      } else {
        const uncertain =
          result.error.kind !== 'http' ||
          result.error.status === null ||
          result.error.status >= 500 ||
          result.error.status === 409;
        updateOutgoing(localId, {
          phase: uncertain ? 'uncertain' : 'rejected',
        });
      }
      return result;
    } catch (error) {
      updateOutgoing(localId, { phase: 'uncertain' });
      throw error;
    } finally {
      sendingRef.current = false;
      if (mounted.current) mutation.reset();
    }
  }

  async function reconcile(): Promise<boolean> {
    try {
      if (!mounted.current) return false;

      const customerId = requireCurrentSession();
      const conversationKey = chatKeys.conversation(customerId, conversationId);

      // Discard reads that started before this reconciliation.
      // This cancels GET requests, never the message mutation.
      await queryClient.cancelQueries({
        queryKey: conversationKey,
      });

      requireCurrentSession();
      if (!mounted.current) return false;

      await queryClient.invalidateQueries({
        queryKey: conversationKey,
        refetchType: 'none',
      });

      const readHistory = (offset: number) =>
        queryClient.fetchQuery({
          queryKey: chatKeys.history(customerId, conversationId, offset),
          staleTime: 0,
          retry: false,
          networkMode: 'always',
          queryFn: async ({ signal }) => {
            requireCurrentSession();

            const result = await api.history(conversationId, { limit: 50, offset }, signal);

            requireCurrentSession();
            return unwrap(result);
          },
        });

      const [, firstPage] = await Promise.all([
        queryClient.fetchQuery({
          queryKey: conversationKey,
          staleTime: 0,
          retry: false,
          networkMode: 'always',
          queryFn: async ({ signal }) => {
            requireCurrentSession();

            const result = await api.get(conversationId, signal);

            requireCurrentSession();
            return unwrap(result);
          },
        }),
        readHistory(0),
      ]);

      requireCurrentSession();
      if (!mounted.current) return false;

      const latestOffset = firstPage.total === 0 ? 0 : Math.floor((firstPage.total - 1) / 50) * 50;

      const latestPage = latestOffset === 0 ? firstPage : await readHistory(latestOffset);

      requireCurrentSession();
      if (!mounted.current) return false;

      onPageChange(latestOffset);

      const pending = outgoingRef.current;
      if (
        pending?.messageId &&
        [...firstPage.items, ...latestPage.items].some(
          (item) => item.message_id === pending.messageId,
        )
      ) {
        publishOutgoing(null);
      }

      // A message can create or change the latest escalation.
      // Failure here must not turn confirmed message reconciliation
      // into a failed send.
      void queryClient
        .invalidateQueries({
          queryKey: customerEscalationKey(customerId, conversationId),
          exact: true,
        })
        .catch(() => undefined);

      // Refresh the rail's status/order without making its availability
      // determine whether conversation reconciliation succeeded.
      void queryClient
        .invalidateQueries({
          queryKey: ['chat', customerId, 'conversations'],
        })
        .catch(() => undefined);

      // Concurrent additions can move the last page while we read.
      // Require another explicit refresh instead of claiming it is current.
      return !latestPage.has_more;
    } catch {
      return false;
    } finally {
      const current = outgoingRef.current;
      if (current?.phase === 'syncing') {
        updateOutgoing(current.localId, { phase: 'saved' });
      }
    }
  }

  return {
    outgoing,
    clearOutgoing,
    send,
    reconcile,
    isPending: mutation.isPending,
  };
}
