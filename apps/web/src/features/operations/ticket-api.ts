// apps/web/src/features/operations/ticket-api.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult, createTransport } from '../../shared/api/transport';
import type { components } from '../../shared/api/generated/schema';
import {
  decodeTicketCommentReceipt,
  decodeTicketDetail,
  decodeTicketPage,
  decodeTicketUpdateResponse,
  ticketCategorySchema,
  ticketCommentVisibilitySchema,
  ticketIdSchema,
  ticketPrioritySchema,
  ticketStatusSchema,
  ticketCustomerMessageSchema,
  type TicketCategory,
  type TicketCommentReceipt,
  type TicketCommentVisibility,
  type TicketDetail,
  type TicketPage,
  type TicketPriority,
  type TicketStatus,
  type TicketUpdateResponse,
} from './ticket-contract';

type Transport = ReturnType<typeof createTransport>;

export interface TicketFilters {
  readonly activeOnly: boolean;
  readonly status: TicketStatus | null;
  readonly priority: TicketPriority | null;
  readonly category: TicketCategory | null;
  readonly assignedAgentId: string | null;
  readonly unassignedOnly: boolean;
  readonly limit: number;
  readonly offset: number;
}

export interface TicketUpdateInput {
  readonly expectedRowVersion: number;
  readonly targetStatus?: TicketStatus | null;
  readonly priority?: TicketPriority | null;
  readonly category?: TicketCategory | null;
  readonly assignedAgentId?: string | null;
  readonly unassign?: boolean;
  readonly resolutionSummary?: string | null;
  /* Required only when transitioning to waiting_for_customer. */
  readonly customerMessage?: string | null;
}

export interface AddTicketCommentInput {
  readonly visibility: TicketCommentVisibility;
  readonly content: string;
}

const ticketFiltersSchema = z
  .object({
    activeOnly: z.boolean(),
    status: ticketStatusSchema.nullable(),
    priority: ticketPrioritySchema.nullable(),
    category: ticketCategorySchema.nullable(),
    assignedAgentId: z.uuid().nullable(),
    unassignedOnly: z.boolean(),
    limit: z.number().int().min(1).max(200),
    offset: z.number().int().nonnegative(),
  })
  .strict()
  .superRefine((filters, context) => {
    if (filters.activeOnly && filters.status !== null) {
      context.addIssue({
        code: 'custom',
        path: ['status'],
        message: 'Status cannot be supplied for the active ticket queue.',
      });
    }

    if (filters.assignedAgentId !== null && filters.unassignedOnly) {
      context.addIssue({
        code: 'custom',
        path: ['assignedAgentId'],
        message: 'Assigned-agent and unassigned-only filters cannot be combined.',
      });
    }
  });

const ticketUpdateInputSchema = z
  .object({
    expectedRowVersion: z.number().int().min(1),
    targetStatus: ticketStatusSchema.nullable().optional(),
    priority: ticketPrioritySchema.nullable().optional(),
    category: ticketCategorySchema.nullable().optional(),
    assignedAgentId: z.uuid().nullable().optional(),
    unassign: z.boolean().default(false),
    resolutionSummary: z.string().trim().min(1).max(5_000).nullable().optional(),
    customerMessage: ticketCustomerMessageSchema.nullable().optional(),
  })
  .strict()
  .superRefine((update, context) => {
    if (
      update.assignedAgentId !== null &&
      update.assignedAgentId !== undefined &&
      update.unassign
    ) {
      context.addIssue({
        code: 'custom',
        path: ['assignedAgentId'],
        message: 'A ticket cannot be assigned and unassigned together.',
      });
    }

    if (
      update.targetStatus === 'resolved' &&
      (update.resolutionSummary === null || update.resolutionSummary === undefined)
    ) {
      context.addIssue({
        code: 'custom',
        path: ['resolutionSummary'],
        message: 'A resolution summary is required when resolving a ticket.',
      });
    }

    if (
      update.targetStatus !== 'resolved' &&
      update.resolutionSummary !== null &&
      update.resolutionSummary !== undefined
    ) {
      context.addIssue({
        code: 'custom',
        path: ['resolutionSummary'],
        message: 'A resolution summary may only be supplied when resolving a ticket.',
      });
    }

    const hasMutation =
      update.targetStatus != null ||
      update.priority != null ||
      update.category != null ||
      update.assignedAgentId != null ||
      update.unassign;

    if (!hasMutation) {
      context.addIssue({
        code: 'custom',
        path: [],
        message: 'At least one ticket mutation must be requested.',
      });
    }

    if (
      update.targetStatus === 'waiting_for_customer' &&
      typeof update.customerMessage !== 'string'
    ) {
      context.addIssue({
        code: 'custom',
        path: ['customerMessage'],
        message: 'Describe the information required from the customer.',
      });
    }

    if (update.targetStatus !== 'waiting_for_customer' && update.customerMessage != null) {
      context.addIssue({
        code: 'custom',
        path: ['customerMessage'],
        message:
          'A customer-facing information request is only allowed when waiting for the customer.',
      });
    }
  });

const addCommentInputSchema = z
  .object({
    visibility: ticketCommentVisibilitySchema,
    content: z.string().trim().min(1).max(20_000),
  })
  .strict();

function requestSignal(signal: AbortSignal | undefined) {
  return signal === undefined ? {} : { signal };
}

function invalidRequest<T>(): Promise<TransportResult<T>> {
  return Promise.resolve({
    ok: false,
    error: SafeApiError.fromLocal('invalid-response'),
    retryAfterMs: null,
  });
}

export function createTicketApi(request: Transport) {
  return {
    list(filters: TicketFilters, signal?: AbortSignal): Promise<TransportResult<TicketPage>> {
      const parsed = ticketFiltersSchema.safeParse(filters);

      if (!parsed.success) {
        return invalidRequest<TicketPage>();
      }

      const query = new URLSearchParams({
        active_only: String(parsed.data.activeOnly),
        unassigned_only: String(parsed.data.unassignedOnly),
        limit: String(parsed.data.limit),
        offset: String(parsed.data.offset),
      });

      if (parsed.data.status !== null) {
        query.set('status', parsed.data.status);
      }

      if (parsed.data.priority !== null) {
        query.set('priority', parsed.data.priority);
      }

      if (parsed.data.category !== null) {
        query.set('category', parsed.data.category);
      }

      if (parsed.data.assignedAgentId !== null) {
        query.set('assigned_agent_id', parsed.data.assignedAgentId);
      }

      return request({
        path: '/v1/tickets',
        method: 'GET',
        authentication: 'bearer',
        query,
        decode: decodeTicketPage,
        ...requestSignal(signal),
      });
    },

    get(ticketId: string, signal?: AbortSignal): Promise<TransportResult<TicketDetail>> {
      const parsedId = ticketIdSchema.safeParse(ticketId);

      if (!parsedId.success) {
        return invalidRequest<TicketDetail>();
      }

      return request({
        path: `/v1/tickets/${parsedId.data}`,
        method: 'GET',
        authentication: 'bearer',
        decode(value) {
          const detail = decodeTicketDetail(value);

          if (detail.ticket.ticket_id !== parsedId.data) {
            throw SafeApiError.fromLocal('invalid-response');
          }

          return detail;
        },
        ...requestSignal(signal),
      });
    },

    update(
      ticketId: string,
      update: TicketUpdateInput,
      signal?: AbortSignal,
    ): Promise<TransportResult<TicketUpdateResponse>> {
      const parsedId = ticketIdSchema.safeParse(ticketId);
      const parsedUpdate = ticketUpdateInputSchema.safeParse(update);

      if (!parsedId.success || !parsedUpdate.success) {
        return invalidRequest<TicketUpdateResponse>();
      }

      const body = {
        expected_row_version: parsedUpdate.data.expectedRowVersion,
        unassign: parsedUpdate.data.unassign,

        ...(parsedUpdate.data.targetStatus != null
          ? { target_status: parsedUpdate.data.targetStatus }
          : {}),

        ...(parsedUpdate.data.priority != null ? { priority: parsedUpdate.data.priority } : {}),

        ...(parsedUpdate.data.category != null ? { category: parsedUpdate.data.category } : {}),

        ...(parsedUpdate.data.assignedAgentId != null
          ? { assigned_agent_id: parsedUpdate.data.assignedAgentId }
          : {}),

        ...(parsedUpdate.data.resolutionSummary != null
          ? { resolution_summary: parsedUpdate.data.resolutionSummary }
          : {}),

        ...(parsedUpdate.data.customerMessage != null
          ? { customer_message: parsedUpdate.data.customerMessage }
          : {}),
      } satisfies components['schemas']['UpdateTicketRequest'];

      return request({
        path: `/v1/tickets/${parsedId.data}`,
        method: 'PATCH',
        authentication: 'bearer',
        body: {
          kind: 'json',
          value: body,
        },
        decode(value) {
          const result = decodeTicketUpdateResponse(value);

          if (result.ticket_id !== parsedId.data) {
            throw SafeApiError.fromLocal('invalid-response');
          }

          return result;
        },
        ...requestSignal(signal),
      });
    },

    addComment(
      ticketId: string,
      comment: AddTicketCommentInput,
      signal?: AbortSignal,
    ): Promise<TransportResult<TicketCommentReceipt>> {
      const parsedId = ticketIdSchema.safeParse(ticketId);
      const parsedComment = addCommentInputSchema.safeParse(comment);

      if (!parsedId.success || !parsedComment.success) {
        return invalidRequest<TicketCommentReceipt>();
      }

      return request({
        path: `/v1/tickets/${parsedId.data}/comments`,
        method: 'POST',
        authentication: 'bearer',
        body: {
          kind: 'json',
          value: {
            visibility: parsedComment.data.visibility,
            content: parsedComment.data.content,
          },
        },
        decode: decodeTicketCommentReceipt,
        ...requestSignal(signal),
      });
    },
  };
}
