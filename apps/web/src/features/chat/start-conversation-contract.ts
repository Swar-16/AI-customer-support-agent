// apps/web/src/features/chat/start-conversation-contract.ts
import { z } from 'zod';

import type { components } from '../../shared/api/generated/schema';
import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResponseContext } from '../../shared/api/transport';

import { conversationIdSchema, sendMessageSchema } from './chat-contract';

export type StartConversationRequest = components['schemas']['StartConversationRequest'];

export type StartConversationResponse = components['schemas']['StartConversationResponse'];

export type StartConversationProcessingResponse =
  components['schemas']['StartConversationProcessingResponse'];

export type StartConversationOutcome =
  | {
      readonly kind: 'processing';
      readonly data: StartConversationProcessingResponse;
      readonly retryAfterMs: number;
    }
  | {
      readonly kind: 'terminal';
      readonly outcome: 'answer' | 'escalated' | 'failed';
      readonly data: StartConversationResponse;
    };

const processingSchema = z.object({
  start_request_id: conversationIdSchema,
  conversation_id: conversationIdSchema,
  idempotency_status: z.literal('processing').default('processing'),
  retry_after_seconds: z.number().int().min(1).max(300),
}) satisfies z.ZodType<StartConversationProcessingResponse>;

const terminalSchema = sendMessageSchema.extend({
  start_request_id: conversationIdSchema,

  idempotency_status: z.enum(['completed', 'failed']),

  created: z.boolean(),
  replayed: z.boolean(),

  failure_code: z.string().min(1).max(100).nullable().default(null),

  failure_retryable: z.boolean().nullable().default(null),
}) satisfies z.ZodType<StartConversationResponse>;

function invalidResponse(): never {
  throw SafeApiError.fromLocal('invalid-response');
}

function hasCommittedAssistantResponse(data: StartConversationResponse): boolean {
  return (
    typeof data.assistant_message_id === 'string' &&
    typeof data.response === 'string' &&
    data.response.trim().length > 0
  );
}

export function decodeStartConversation(
  value: unknown,
  context: TransportResponseContext,
): StartConversationOutcome {
  if (context.status === 202) {
    const parsed = processingSchema.safeParse(value);

    if (!parsed.success) {
      return invalidResponse();
    }

    const bodyDelayMs = parsed.data.retry_after_seconds * 1_000;

    const headerDelayMs = context.retryAfterMs;

    if (headerDelayMs !== null && (!Number.isFinite(headerDelayMs) || headerDelayMs < 0)) {
      return invalidResponse();
    }

    return {
      kind: 'processing',
      data: parsed.data,

      /*
       * Respect both server-provided delays. The coordinator separately
       * controls the maximum number of recovery attempts.
       */
      retryAfterMs: Math.max(bodyDelayMs, headerDelayMs ?? 0),
    };
  }

  if (context.status !== 200 && context.status !== 201) {
    return invalidResponse();
  }

  const parsed = terminalSchema.safeParse(value);

  if (!parsed.success) {
    return invalidResponse();
  }

  const data = parsed.data;

  const expectedCreated = context.status === 201;

  if (data.created !== expectedCreated || (data.created && data.replayed)) {
    return invalidResponse();
  }

  /*
   * A failed pipeline must not contain a fabricated assistant response or
   * escalation identity.
   */
  if (!data.succeeded) {
    if (
      data.idempotency_status !== 'failed' ||
      data.pipeline_stage !== 'failed' ||
      data.failure_code === null ||
      data.failure_retryable === null ||
      data.assistant_message_id !== null ||
      data.response !== null ||
      data.escalation_id !== null
    ) {
      return invalidResponse();
    }

    return {
      kind: 'terminal',
      outcome: 'failed',
      data,
    };
  }

  /*
   * All successful terminal outcomes must be completed and must not contain
   * failure metadata.
   */
  if (
    data.idempotency_status !== 'completed' ||
    data.failure_code !== null ||
    data.failure_retryable !== null
  ) {
    return invalidResponse();
  }

  /*
   * Normal completed assistant answer.
   */
  if (
    data.pipeline_stage === 'guardrails_completed' &&
    hasCommittedAssistantResponse(data) &&
    data.escalation_id === null
  ) {
    return {
      kind: 'terminal',
      outcome: 'answer',
      data,
    };
  }

  /*
   * Escalation is a successful completed outcome.
   *
   * The backend now persists a safe customer-visible assistant notice and
   * returns both its message ID and content.
   */
  if (
    data.pipeline_stage === 'escalated' &&
    data.escalation_id !== null &&
    hasCommittedAssistantResponse(data)
  ) {
    return {
      kind: 'terminal',
      outcome: 'escalated',
      data,
    };
  }

  /*
   * Unknown or contradictory combinations must not become fake success.
   */
  return invalidResponse();
}
