// apps/web/src/features/operations/escalation-contract.ts
import { z } from 'zod';

import type { components } from '../../shared/api/generated/schema';
import { SafeApiError } from '../../shared/api/safe-error';

export const escalationStatusSchema = z.enum(['open', 'in_review', 'resolved', 'dismissed']);
export const escalationPrioritySchema = z.enum(['low', 'normal', 'high', 'urgent']);
export const escalationSourceSchema = z.enum(['decision', 'guardrail', 'system', 'manual']);

export const ticketStatusSchema = z.enum([
  'open',
  'in_progress',
  'waiting_for_customer',
  'resolved',
  'closed',
  'reopened',
]);
export const ticketCategorySchema = z.enum([
  'billing',
  'refund',
  'order',
  'account',
  'technical',
  'security',
  'product',
  'general',
  'other',
]);

export const escalationIdSchema = z.uuid();
export const escalationConversationIdSchema = z.uuid();
export const escalationCustomerMessageSchema = z
  .string()
  .trim()
  .min(1, 'Enter a customer-facing explanation.')
  .max(2_000, 'Use 2,000 characters or fewer.');

export const escalationTransitionRequestSchema = z
  .object({
    status: escalationStatusSchema,

    customer_message: escalationCustomerMessageSchema.nullable().default(null),
  })
  .strict()
  .superRefine((request, context) => {
    const terminal = request.status === 'resolved' || request.status === 'dismissed';

    if (terminal && typeof request.customer_message !== 'string') {
      context.addIssue({
        code: 'custom',
        path: ['customer_message'],
        message: 'A customer-facing explanation is required for this status.',
      });
    }

    if (!terminal && request.customer_message != null) {
      context.addIssue({
        code: 'custom',
        path: ['customer_message'],
        message:
          'A customer-facing explanation is only allowed for resolved or dismissed escalations.',
      });
    }
  }) satisfies z.ZodType<components['schemas']['UpdateEscalationRequest']>;

const timestampSchema = z.iso.datetime({ offset: true });

export const escalationSchema = z
  .object({
    escalation_id: escalationIdSchema,
    conversation_id: escalationConversationIdSchema,
    ai_run_id: z.uuid().nullable().default(null),
    trigger_message_id: z.uuid().nullable().default(null),
    source: escalationSourceSchema,
    reason_code: z.string().min(1).max(100),
    reason_summary: z.string().max(2_000).nullable().default(null),
    priority: escalationPrioritySchema,
    status: escalationStatusSchema,
    handoff_summary: z.string().max(5_000).nullable().default(null),
    metadata: z.record(z.string(), z.unknown()).default({}),
    created_at: timestampSchema,
    updated_at: timestampSchema,
    resolved_at: timestampSchema.nullable().default(null),
  })
  .strict();

export const escalationPageSchema = z
  .object({
    items: z.array(escalationSchema),
    count: z.number().int().nonnegative(),
    limit: z.number().int().min(1).max(200),
    offset: z.number().int().nonnegative(),
    has_more: z.boolean(),
  })
  .strict()
  .superRefine((page, context) => {
    if (page.items.length > page.limit) {
      context.addIssue({
        code: 'custom',
        path: ['items'],
        message: 'The escalation page contains more items than its limit.',
      });
    }

    const escalationIds = new Set<string>();

    page.items.forEach((item, index) => {
      if (escalationIds.has(item.escalation_id)) {
        context.addIssue({
          code: 'custom',
          path: ['items', index, 'escalation_id'],
          message: 'Escalation identifiers must be unique within a page.',
        });
      }

      escalationIds.add(item.escalation_id);
    });
  });

export const escalationUpdateSchema = z
  .object({
    escalation_id: z.uuid(),
    conversation_id: z.uuid(),
    ai_run_id: z.uuid().nullable().default(null),
    previous_status: escalationStatusSchema,
    current_status: escalationStatusSchema,
    resolved_at: timestampSchema.nullable().default(null),
    updated_at: timestampSchema,
    changed: z.boolean(),
  })
  .strict();

export const linkedEscalationTicketSchema = z.object({
  ticket_id: z.uuid(),
  ticket_number: z.number().int().positive(),
  ticket_reference: z.string().trim().min(1).max(32),
  status: ticketStatusSchema,
}) satisfies z.ZodType<LinkedEscalationTicket>;

export const escalationDetailSchema = escalationSchema.extend({
  linked_ticket: linkedEscalationTicketSchema.nullable().default(null),
}) satisfies z.ZodType<EscalationDetail>;

export const escalationTicketDraftSchema = z.object({
  subject: z.string().trim().min(1).max(300),
  description: z.string().trim().min(1).max(20_000),
  category: ticketCategorySchema,
  priority: escalationPrioritySchema,
}) satisfies z.ZodType<EscalationTicketDraft>;

export const createdEscalationTicketSchema = z.object({
  ticket_id: z.uuid(),
  ticket_number: z.number().int().positive(),
  ticket_reference: z.string().trim().min(1).max(32),
  conversation_id: z.uuid(),
  customer_id: z.uuid(),
  escalation_id: z.uuid().nullable().default(null),
  status: ticketStatusSchema,
  priority: escalationPrioritySchema,
  category: ticketCategorySchema,
  created: z.boolean(),
}) satisfies z.ZodType<CreatedEscalationTicket>;

export type EscalationStatus = z.infer<typeof escalationStatusSchema>;
export type EscalationPriority = z.infer<typeof escalationPrioritySchema>;
export type EscalationSource = z.infer<typeof escalationSourceSchema>;
export type Escalation = z.infer<typeof escalationSchema>;
export type EscalationPage = z.infer<typeof escalationPageSchema>;
export type EscalationUpdate = z.infer<typeof escalationUpdateSchema>;
export type EscalationDetail = Escalation & {
  readonly linked_ticket: LinkedEscalationTicket | null;
};
export type LinkedEscalationTicket = components['schemas']['LinkedEscalationTicketResponse'];
export type EscalationTicketDraft = components['schemas']['CreateEscalationTicketRequest'];
export type CreatedEscalationTicket = components['schemas']['CreateTicketResponse'];
export type EscalationTransitionRequest = components['schemas']['UpdateEscalationRequest'];

export function decodeEscalation(value: unknown): Escalation {
  return escalationSchema.parse(value);
}

export function decodeEscalationPage(value: unknown): EscalationPage {
  return escalationPageSchema.parse(value);
}

export function decodeEscalationUpdate(value: unknown): EscalationUpdate {
  return escalationUpdateSchema.parse(value);
}

export function decodeEscalationDetail(value: unknown): EscalationDetail {
  const parsed = escalationDetailSchema.safeParse(value);

  if (!parsed.success) {
    throw SafeApiError.fromLocal('invalid-response');
  }

  const ticket = parsed.data.linked_ticket;

  if (
    ticket !== null &&
    (!ticket.ticket_reference.startsWith('TKT-') || ticket.ticket_number <= 0)
  ) {
    throw SafeApiError.fromLocal('invalid-response');
  }

  return parsed.data;
}

export function decodeCreatedEscalationTicket(value: unknown): CreatedEscalationTicket {
  const parsed = createdEscalationTicketSchema.safeParse(value);

  if (!parsed.success) {
    throw SafeApiError.fromLocal('invalid-response');
  }

  return parsed.data;
}
