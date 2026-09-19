// apps/web/src/features/operations/escalation-contract.ts
import { z } from 'zod';

export const escalationStatusSchema = z.enum(['open', 'in_review', 'resolved', 'dismissed']);

export const escalationPrioritySchema = z.enum(['low', 'normal', 'high', 'urgent']);

export const escalationSourceSchema = z.enum(['decision', 'guardrail', 'system', 'manual']);

export const escalationIdSchema = z.uuid();
export const escalationConversationIdSchema = z.uuid();

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

export type EscalationStatus = z.infer<typeof escalationStatusSchema>;
export type EscalationPriority = z.infer<typeof escalationPrioritySchema>;
export type EscalationSource = z.infer<typeof escalationSourceSchema>;
export type Escalation = z.infer<typeof escalationSchema>;
export type EscalationPage = z.infer<typeof escalationPageSchema>;
export type EscalationUpdate = z.infer<typeof escalationUpdateSchema>;

export function decodeEscalation(value: unknown): Escalation {
  return escalationSchema.parse(value);
}

export function decodeEscalationPage(value: unknown): EscalationPage {
  return escalationPageSchema.parse(value);
}

export function decodeEscalationUpdate(value: unknown): EscalationUpdate {
  return escalationUpdateSchema.parse(value);
}
