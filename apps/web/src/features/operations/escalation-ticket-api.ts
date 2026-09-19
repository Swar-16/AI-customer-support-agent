// apps/web/src/features/operations/escalation-ticket-api.ts
import { z } from 'zod';

import type { components } from '../../shared/api/generated/schema';
import { SafeApiError } from '../../shared/api/safe-error';
import type { createTransport, TransportResult } from '../../shared/api/transport';
import { decodeCreatedEscalationTicket, escalationTicketDraftSchema } from './escalation-contract';
import type { CreatedEscalationTicket, EscalationTicketDraft } from './escalation-contract';

type Transport = ReturnType<typeof createTransport>;

const escalationIdSchema = z.uuid();

function invalidRequest(): Promise<TransportResult<CreatedEscalationTicket>> {
  return Promise.resolve({
    ok: false,
    error: SafeApiError.fromLocal('invalid-response'),
    retryAfterMs: null,
  });
}

function requestSignal(signal: AbortSignal | undefined) {
  return signal === undefined ? {} : { signal };
}

export function createEscalationTicketApi(request: Transport) {
  return {
    create(
      escalationId: string,
      draft: EscalationTicketDraft,
      signal?: AbortSignal,
    ): Promise<TransportResult<CreatedEscalationTicket>> {
      const parsedId = escalationIdSchema.safeParse(escalationId);
      const parsedDraft = escalationTicketDraftSchema.safeParse(draft);

      if (!parsedId.success || !parsedDraft.success) {
        return invalidRequest();
      }

      const body = {
        subject: parsedDraft.data.subject,
        description: parsedDraft.data.description,
        category: parsedDraft.data.category,
        priority: parsedDraft.data.priority,
      } satisfies components['schemas']['CreateEscalationTicketRequest'];

      return request({
        path: `/v1/escalations/${parsedId.data}/ticket`,
        method: 'POST',
        authentication: 'bearer',
        body: {
          kind: 'json',
          value: body,
        },
        decode(value) {
          const ticket = decodeCreatedEscalationTicket(value);

          if (ticket.escalation_id !== parsedId.data) {
            throw SafeApiError.fromLocal('invalid-response');
          }

          return ticket;
        },
        ...requestSignal(signal),
      });
    },
  };
}
