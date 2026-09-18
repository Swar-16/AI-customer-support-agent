// apps/web/src/features/chat/start-conversation-api.ts
import { SafeApiError } from '../../shared/api/safe-error';
import type { createTransport, TransportResult } from '../../shared/api/transport';

import { customerMessageSchema } from './chat-contract';
import {
  decodeStartConversation,
  type StartConversationOutcome,
  type StartConversationRequest,
} from './start-conversation-contract';

type Transport = ReturnType<typeof createTransport>;

export interface StartConversationInput {
  readonly message: string;
  readonly idempotencyKey: string;
}

const IDEMPOTENCY_KEY_PATTERN = /^[!-~]{16,255}$/u;

export function createStartConversationApi(request: Transport) {
  return {
    async start(
      input: StartConversationInput,
      signal?: AbortSignal,
    ): Promise<TransportResult<StartConversationOutcome>> {
      const message = customerMessageSchema.safeParse(input.message);

      if (!message.success || !IDEMPOTENCY_KEY_PATTERN.test(input.idempotencyKey)) {
        return {
          ok: false,
          error: SafeApiError.fromLocal('invalid-response'),
          retryAfterMs: null,
        };
      }

      const body = {
        message: message.data,
        channel: 'web',
      } satisfies StartConversationRequest;

      return request({
        path: '/v1/conversations/start',
        method: 'POST',
        authentication: 'bearer',
        idempotencyKey: input.idempotencyKey,
        body: { kind: 'json', value: body },
        decode: decodeStartConversation,
        ...(signal === undefined ? {} : { signal }),
      });
    },
  };
}

export type StartConversationApi = ReturnType<typeof createStartConversationApi>;
