// apps/web/src/features/chat/start-conversation-coordinator.ts
import { SafeApiError } from '../../shared/api/safe-error';

import { customerMessageSchema } from './chat-contract';
import type { StartConversationApi } from './start-conversation-api';
import type { StartConversationOutcome } from './start-conversation-contract';

type TerminalOutcome = Extract<StartConversationOutcome, { kind: 'terminal' }>;

export type StartConversationState =
  | { readonly phase: 'idle' }
  | { readonly phase: 'pending'; readonly attempt: number }
  | {
      readonly phase: 'processing';
      readonly conversationId: string;
      readonly retryAt: number;
      readonly attemptsRemaining: number;
    }
  | {
      readonly phase: 'uncertain';
      readonly error: SafeApiError;
      readonly retryAt: number;
      readonly attemptsRemaining: number;
    }
  | {
      readonly phase: 'blocked';
      readonly error: SafeApiError;
    }
  | {
      readonly phase: 'terminal';
      readonly result: TerminalOutcome;
    }
  | { readonly phase: 'disposed' };

interface Dependencies {
  readonly api: StartConversationApi;
  readonly createKey?: () => string;
  readonly now?: () => number;
}

const MAX_ATTEMPTS = 5;
const MIN_RECOVERY_DELAY_MS = 1_000;
const KEY_PATTERN = /^[!-~]{16,255}$/u;

export function createStartConversationCoordinator({
  api,
  createKey = () => crypto.randomUUID(),
  now = () => Date.now(),
}: Dependencies) {
  let state: StartConversationState = { phase: 'idle' };
  let submission: Readonly<{
    message: string;
    idempotencyKey: string;
  }> | null = null;

  let attempts = 0;
  let controller: AbortController | null = null;
  let disposed = false;

  let acceptedIdentity: Readonly<{
    conversationId: string;
    startRequestId: string;
  }> | null = null;

  const listeners = new Set<() => void>();

  function publish(next: StartConversationState) {
    state = next;
    for (const listener of listeners) {
      listener();
    }
  }

  function clearSubmission() {
    submission = null;
    acceptedIdentity = null;
  }

  function recoveryTime(delay: number | null): number {
    const safeDelay = delay !== null && Number.isFinite(delay) && delay >= 0 ? delay : 0;

    return now() + Math.max(MIN_RECOVERY_DELAY_MS, safeDelay);
  }

  function handleFailure(error: SafeApiError, retryAfterMs: number | null) {
    // Only local/unknown outcomes and 503 allow explicit same-key recovery.
    // Authentication, conflicts, and validation errors require separate handling.
    if (error.status == null || error.status === 503) {
      publish({
        phase: 'uncertain',
        error,
        retryAt: recoveryTime(retryAfterMs),
        attemptsRemaining: MAX_ATTEMPTS - attempts,
      });
      return;
    }

    clearSubmission();
    publish({ phase: 'blocked', error });
  }

  async function execute(): Promise<void> {
    if (disposed || submission === null || controller !== null) {
      return;
    }

    const currentSubmission = submission;
    const currentController = new AbortController();
    controller = currentController;
    attempts += 1;

    publish({ phase: 'pending', attempt: attempts });

    // A subscriber may dispose the coordinator after the pending notification.
    if (disposed) {
      return;
    }

    try {
      const result = await api.start(currentSubmission, currentController.signal);

      if (disposed || controller !== currentController) {
        return;
      }

      if (!result.ok) {
        handleFailure(result.error, result.retryAfterMs);
        return;
      }

      const identity = {
        conversationId: result.data.data.conversation_id,
        startRequestId: result.data.data.start_request_id,
      };

      if (
        acceptedIdentity !== null &&
        (identity.conversationId !== acceptedIdentity.conversationId ||
          identity.startRequestId !== acceptedIdentity.startRequestId)
      ) {
        clearSubmission();
        publish({
          phase: 'blocked',
          error: SafeApiError.fromLocal('invalid-response'),
        });
        return;
      }

      acceptedIdentity = identity;

      if (result.data.kind === 'processing') {
        publish({
          phase: 'processing',
          conversationId: identity.conversationId,
          retryAt: recoveryTime(result.data.retryAfterMs),
          attemptsRemaining: MAX_ATTEMPTS - attempts,
        });
        return;
      }

      clearSubmission();
      publish({
        phase: 'terminal',
        result: result.data,
      });
    } catch {
      if (!disposed && controller === currentController) {
        // Never retain an exception that may contain request content.
        handleFailure(SafeApiError.fromLocal('network'), null);
      }
    } finally {
      if (controller === currentController) {
        controller = null;
      }
    }
  }

  async function submit(message: string): Promise<void> {
    // This coordinator represents exactly one draft submission.
    if (disposed || state.phase !== 'idle') {
      return;
    }

    const parsed = customerMessageSchema.safeParse(message);

    if (!parsed.success) {
      // Form validation owns the visible validation message.
      return;
    }

    let idempotencyKey: string;

    try {
      idempotencyKey = createKey();
    } catch {
      publish({
        phase: 'blocked',
        error: SafeApiError.fromLocal('invalid-response'),
      });
      return;
    }

    if (!KEY_PATTERN.test(idempotencyKey)) {
      publish({
        phase: 'blocked',
        error: SafeApiError.fromLocal('invalid-response'),
      });
      return;
    }

    submission = Object.freeze({
      message: parsed.data,
      idempotencyKey,
    });

    await execute();
  }

  async function recover(): Promise<void> {
    if (
      disposed ||
      controller !== null ||
      (state.phase !== 'processing' && state.phase !== 'uncertain') ||
      state.attemptsRemaining === 0 ||
      now() < state.retryAt
    ) {
      return;
    }

    await execute();
  }

  function dispose() {
    if (disposed) {
      return;
    }

    disposed = true;
    controller?.abort();
    controller = null;
    clearSubmission();
    publish({ phase: 'disposed' });
    listeners.clear();
  }

  return {
    getSnapshot: (): StartConversationState => state,
    subscribe(listener: () => void) {
      if (disposed) {
        return () => {};
      }

      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    submit,
    recover,
    dispose,
  };
}

export type StartConversationCoordinator = ReturnType<typeof createStartConversationCoordinator>;
