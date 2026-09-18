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
      // Wait at least as long as both server-provided delays.
      // The coordinator will separately bound its number of attempts.
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

  if (data.created !== (context.status === 201) || (data.created && data.replayed)) {
    return invalidResponse();
  }

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

  if (
    data.idempotency_status !== 'completed' ||
    data.failure_code !== null ||
    data.failure_retryable !== null
  ) {
    return invalidResponse();
  }

  if (
    data.pipeline_stage === 'guardrails_completed' &&
    data.assistant_message_id !== null &&
    data.response !== null &&
    data.response.trim().length > 0 &&
    data.escalation_id === null
  ) {
    return {
      kind: 'terminal',
      outcome: 'answer',
      data,
    };
  }

  if (
    data.pipeline_stage === 'escalated' &&
    data.escalation_id !== null &&
    data.assistant_message_id === null &&
    data.response === null
  ) {
    return {
      kind: 'terminal',
      outcome: 'escalated',
      data,
    };
  }

  // Unknown or contradictory outcomes must never become fake success.
  return invalidResponse();
}
