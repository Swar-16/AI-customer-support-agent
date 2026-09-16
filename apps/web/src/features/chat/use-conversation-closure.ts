import { useRef, useState } from 'react';
import type { RefObject } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import { useSession, useSessionController } from '../../shared/auth/session-context';
import type { Conversation } from './chat-contract';
import { chatKeys, useChatApi } from './chat-queries';

interface ClosureOptions {
  readonly conversationId: string;
  readonly mutationLockRef: RefObject<'send' | 'close' | null>;
}

export function useConversationClosure({ conversationId, mutationLockRef }: ClosureOptions) {
  const api = useChatApi();
  const queryClient = useQueryClient();
  const session = useSession();
  const controller = useSessionController();

  const [phase, setPhase] = useState<'idle' | 'pending' | 'uncertain' | 'confirmed'>('idle');
  const [notice, setNotice] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [canRetry, setCanRetry] = useState(false);
  const checkingRef = useRef(false);
  const closingRef = useRef(false);

  function requireSession() {
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
    networkMode: 'always',
    gcTime: 0,
    mutationFn: async () => {
      requireSession();
      const result = await api.close(conversationId);
      requireSession();
      return result;
    },
  });

  async function refreshLists(customerId: string) {
    await queryClient.invalidateQueries({
      queryKey: ['chat', customerId, 'conversations'],
    });
  }

  async function checkStatus() {
    if (checkingRef.current || closingRef.current) return;

    checkingRef.current = true;
    setChecking(true);
    setCanRetry(false);

    try {
      const customerId = requireSession();
      const key = chatKeys.conversation(customerId, conversationId);

      await queryClient.cancelQueries({ queryKey: key, exact: true });
      requireSession();

      const conversation = await queryClient.fetchQuery({
        queryKey: key,
        staleTime: 0,
        retry: false,
        networkMode: 'always',
        queryFn: async ({ signal }) => {
          requireSession();
          const result = await api.get(conversationId, signal);
          requireSession();

          if (!result.ok) throw result.error;
          return result.data;
        },
      });

      requireSession();

      if (conversation.status === 'closed') {
        setPhase('confirmed');
        setNotice('This conversation is closed.');
        void refreshLists(customerId).catch(() => undefined);
      } else {
        setPhase('uncertain');
        setCanRetry(true);
        setNotice(
          'The conversation is currently not closed. The earlier request may still be processing. You may check again or explicitly confirm another close request.',
        );
      }
    } catch {
      if (controller.getSnapshot() !== session) return;

      setNotice(
        'The current status could not be loaded. Closure remains unconfirmed and sending is paused.',
      );
    } finally {
      checkingRef.current = false;
      setChecking(false);
    }
  }

  async function close() {
    if (
      closingRef.current ||
      checkingRef.current ||
      mutationLockRef.current === 'send' ||
      phase === 'confirmed' ||
      (mutationLockRef.current === 'close' && !canRetry)
    ) {
      return;
    }

    // Set synchronously before the mutation begins.
    closingRef.current = true;
    mutationLockRef.current = 'close';
    setPhase('pending');
    setCanRetry(false);
    setNotice(null);

    try {
      const customerId = requireSession();
      const result = await mutation.mutateAsync();
      requireSession();

      if (!result.ok) {
        const uncertain =
          result.error.kind !== 'http' ||
          result.error.status === null ||
          result.error.status >= 500;

        if (uncertain) {
          setPhase('uncertain');
          setNotice(
            'Closure could not be confirmed. Check the current conversation status before taking another action.',
          );
        } else {
          mutationLockRef.current = null;
          setPhase('idle');
          setNotice(result.error.message);
        }

        return;
      }

      if (result.data.customer_id !== customerId) {
        throw SafeApiError.fromLocal('invalid-response');
      }

      const key = chatKeys.conversation(customerId, conversationId);

      // Prevent an older GET from overwriting the confirmed closed state.
      await queryClient.cancelQueries({ queryKey: key, exact: true });
      requireSession();

      const closed = result.data;

      queryClient.setQueryData<Conversation>(key, (previous) =>
        previous
          ? {
              ...previous,
              status: closed.status,
              resolved_at: closed.resolved_at,
              closed_at: closed.closed_at,
              updated_at: closed.updated_at,
            }
          : undefined,
      );

      setPhase('confirmed');
      setNotice(closed.changed ? 'Conversation closed.' : 'This conversation was already closed.');

      void refreshLists(customerId).catch(() => undefined);
    } catch {
      if (controller.getSnapshot() !== session) return;

      setPhase('uncertain');
      setNotice(
        'Closure could not be confirmed. Check the current conversation status before taking another action.',
      );
    } finally {
      closingRef.current = false;
      mutation.reset();
    }
  }

  return {
    close,
    checkStatus,
    phase,
    notice,
    checking,
    canRetry,
    blocksSending: phase !== 'idle',
  };
}
