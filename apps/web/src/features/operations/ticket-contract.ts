// apps/web/src/features/operations/ticket-contract.ts
import { z } from 'zod';

export const ticketStatusSchema = z.enum([
  'open',
  'in_progress',
  'waiting_for_customer',
  'resolved',
  'closed',
  'reopened',
]);

export const ticketPrioritySchema = z.enum(['low', 'normal', 'high', 'urgent']);

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

export const ticketSourceSchema = z.enum(['customer', 'escalation', 'agent', 'system']);

export const ticketCommentVisibilitySchema = z.enum(['customer', 'internal']);

export const ticketCommentAuthorRoleSchema = z.enum([
  'customer',
  'support_agent',
  'admin',
  'system',
]);

export const ticketIdSchema = z.uuid();

const timestampSchema = z.iso.datetime({ offset: true });

export const ticketSchema = z
  .object({
    ticket_id: ticketIdSchema,
    ticket_number: z.number().int().nonnegative(),
    ticket_reference: z.string().min(1),
    conversation_id: z.uuid(),
    customer_id: z.uuid(),
    source_message_id: z.uuid().nullable().default(null),
    escalation_id: z.uuid().nullable().default(null),
    assigned_agent_id: z.uuid().nullable().default(null),
    source: ticketSourceSchema,
    subject: z.string().min(1).max(300),
    description: z.string().min(1).max(20_000),
    category: ticketCategorySchema,
    priority: ticketPrioritySchema,
    status: ticketStatusSchema,
    resolution_summary: z.string().nullable().default(null),
    metadata: z.record(z.string(), z.unknown()).default({}),
    row_version: z.number().int().min(1),
    created_at: timestampSchema,
    updated_at: timestampSchema,
    assigned_at: timestampSchema.nullable().default(null),
    resolved_at: timestampSchema.nullable().default(null),
    closed_at: timestampSchema.nullable().default(null),
  })
  .strict();

export const ticketCommentSchema = z
  .object({
    comment_id: z.uuid(),
    ticket_id: ticketIdSchema,
    author_id: z.uuid().nullable().default(null),
    author_role: ticketCommentAuthorRoleSchema,
    visibility: ticketCommentVisibilitySchema,
    content: z.string().min(1),
    metadata: z.record(z.string(), z.unknown()).default({}),
    created_at: timestampSchema,
  })
  .strict();

export const ticketDetailSchema = z
  .object({
    ticket: ticketSchema,
    comments: z.array(ticketCommentSchema),
  })
  .strict()
  .superRefine((detail, context) => {
    const commentIds = new Set<string>();

    detail.comments.forEach((comment, index) => {
      if (comment.ticket_id !== detail.ticket.ticket_id) {
        context.addIssue({
          code: 'custom',
          path: ['comments', index, 'ticket_id'],
          message: 'Every comment must belong to the returned ticket.',
        });
      }

      if (commentIds.has(comment.comment_id)) {
        context.addIssue({
          code: 'custom',
          path: ['comments', index, 'comment_id'],
          message: 'Comment identifiers must be unique within a ticket.',
        });
      }

      commentIds.add(comment.comment_id);
    });
  });

export const ticketPageSchema = z
  .object({
    items: z.array(ticketSchema),
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
        message: 'The ticket page contains more items than its limit.',
      });
    }

    const ticketIds = new Set<string>();

    page.items.forEach((ticket, index) => {
      if (ticketIds.has(ticket.ticket_id)) {
        context.addIssue({
          code: 'custom',
          path: ['items', index, 'ticket_id'],
          message: 'Ticket identifiers must be unique within a page.',
        });
      }

      ticketIds.add(ticket.ticket_id);
    });
  });

export const ticketUpdateResponseSchema = z
  .object({
    ticket_id: ticketIdSchema,
    ticket_number: z.number().int().nonnegative(),
    ticket_reference: z.string().min(1),
    conversation_id: z.uuid(),
    customer_id: z.uuid(),
    previous_status: ticketStatusSchema,
    current_status: ticketStatusSchema,
    priority: ticketPrioritySchema,
    category: ticketCategorySchema,
    assigned_agent_id: z.uuid().nullable().default(null),
    resolution_summary: z.string().nullable().default(null),
    row_version: z.number().int().min(1),
    assigned_at: timestampSchema.nullable().default(null),
    resolved_at: timestampSchema.nullable().default(null),
    closed_at: timestampSchema.nullable().default(null),
    updated_at: timestampSchema,
    changed: z.boolean(),
  })
  .strict();

export const ticketCommentReceiptSchema = z
  .object({
    comment_id: z.uuid(),
    ticket_id: ticketIdSchema,
    author_id: z.uuid().nullable().default(null),
    author_role: ticketCommentAuthorRoleSchema,
    visibility: ticketCommentVisibilitySchema,
    content: z.string().min(1),
    created_at: timestampSchema,
  })
  .strict();

export type TicketStatus = z.infer<typeof ticketStatusSchema>;
export type TicketPriority = z.infer<typeof ticketPrioritySchema>;
export type TicketCategory = z.infer<typeof ticketCategorySchema>;
export type TicketCommentVisibility = z.infer<typeof ticketCommentVisibilitySchema>;
export type Ticket = z.infer<typeof ticketSchema>;
export type TicketComment = z.infer<typeof ticketCommentSchema>;
export type TicketDetail = z.infer<typeof ticketDetailSchema>;
export type TicketPage = z.infer<typeof ticketPageSchema>;
export type TicketUpdateResponse = z.infer<typeof ticketUpdateResponseSchema>;
export type TicketCommentReceipt = z.infer<typeof ticketCommentReceiptSchema>;

export function decodeTicket(value: unknown): Ticket {
  return ticketSchema.parse(value);
}

export function decodeTicketPage(value: unknown): TicketPage {
  return ticketPageSchema.parse(value);
}

export function decodeTicketDetail(value: unknown): TicketDetail {
  return ticketDetailSchema.parse(value);
}

export function decodeTicketUpdateResponse(value: unknown): TicketUpdateResponse {
  return ticketUpdateResponseSchema.parse(value);
}

export function decodeTicketCommentReceipt(value: unknown): TicketCommentReceipt {
  return ticketCommentReceiptSchema.parse(value);
}
