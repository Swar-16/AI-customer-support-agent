// apps/web/src/features/operations/ai-trace-contract.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';

export const traceIdSchema = z.uuid();

export const traceStatusSchema = z.enum(['success', 'error', 'running']);

const timestampSchema = z.iso.datetime({
  offset: true,
});

const nonnegativeIntegerSchema = z.number().int().nonnegative();

const traceDetailValueSchema = z.union([z.string(), z.number(), z.boolean(), z.null()]);

export const traceSummarySchema = z
  .object({
    trace_id: traceIdSchema,
    first_seen_at: timestampSchema,
    last_seen_at: timestampSchema,
    status: traceStatusSchema,

    api_request_count: nonnegativeIntegerSchema,
    ai_run_count: nonnegativeIntegerSchema,
    failed_api_request_count: nonnegativeIntegerSchema,
    failed_ai_run_count: nonnegativeIntegerSchema,
    running_ai_run_count: nonnegativeIntegerSchema,

    maximum_ai_latency_ms: nonnegativeIntegerSchema.nullable().default(null),

    maximum_api_latency_ms: nonnegativeIntegerSchema.nullable().default(null),
  })
  .strict()
  .superRefine((trace, context) => {
    if (Date.parse(trace.first_seen_at) > Date.parse(trace.last_seen_at)) {
      context.addIssue({
        code: 'custom',
        path: ['last_seen_at'],
        message: 'Trace last-seen time cannot precede first-seen time.',
      });
    }

    if (trace.failed_api_request_count > trace.api_request_count) {
      context.addIssue({
        code: 'custom',
        path: ['failed_api_request_count'],
        message: 'Failed API requests cannot exceed total API requests.',
      });
    }

    if (trace.failed_ai_run_count + trace.running_ai_run_count > trace.ai_run_count) {
      context.addIssue({
        code: 'custom',
        path: ['ai_run_count'],
        message: 'Failed and running AI runs cannot exceed total AI runs.',
      });
    }
  });

export const tracePageSchema = z
  .object({
    items: z.array(traceSummarySchema),
    total: nonnegativeIntegerSchema,
    count: nonnegativeIntegerSchema,
    limit: z.number().int().min(1).max(500),
    offset: nonnegativeIntegerSchema,
    has_more: z.boolean(),
    next_offset: nonnegativeIntegerSchema.nullable().default(null),
  })
  .strict();

export const traceComponentCountsSchema = z
  .object({
    api_requests: nonnegativeIntegerSchema,
    ai_runs: nonnegativeIntegerSchema,
    stage_events: nonnegativeIntegerSchema,
    llm_calls: nonnegativeIntegerSchema,
    embedding_calls: nonnegativeIntegerSchema,
    retrieval_runs: nonnegativeIntegerSchema,
    retrieval_candidates: nonnegativeIntegerSchema,
    reranker_calls: nonnegativeIntegerSchema,
    escalations: nonnegativeIntegerSchema,
    tickets: nonnegativeIntegerSchema,
    feedback: nonnegativeIntegerSchema,
    audit_events: nonnegativeIntegerSchema,
  })
  .strict();

export const traceTimelineEventSchema = z
  .object({
    id: z.uuid(),
    category: z.string().trim().min(1).max(64),
    event_type: z.string().trim().min(1).max(100),
    occurred_at: timestampSchema,

    status: z.string().trim().max(32).nullable().default(null),

    duration_ms: nonnegativeIntegerSchema.nullable().default(null),

    details: z.record(z.string(), traceDetailValueSchema).default({}),
  })
  .strict();

export const traceDetailSchema = z
  .object({
    trace_id: traceIdSchema,
    status: traceStatusSchema,
    started_at: timestampSchema,
    ended_at: timestampSchema.nullable(),
    duration_ms: nonnegativeIntegerSchema.nullable().default(null),

    conversation_ids: z.array(z.uuid()),
    ai_run_ids: z.array(z.uuid()),

    component_counts: traceComponentCountsSchema,
    timeline: z.array(traceTimelineEventSchema),
  })
  .strict()
  .superRefine((trace, context) => {
    if (trace.ended_at !== null && Date.parse(trace.started_at) > Date.parse(trace.ended_at)) {
      context.addIssue({
        code: 'custom',
        path: ['ended_at'],
        message: 'Trace end time cannot precede its start.',
      });
    }

    const eventIds = new Set<string>();
    let previousTimestamp = Number.NEGATIVE_INFINITY;

    trace.timeline.forEach((event, index) => {
      if (eventIds.has(event.id)) {
        context.addIssue({
          code: 'custom',
          path: ['timeline', index, 'id'],
          message: 'Trace timeline event identifiers must be unique.',
        });
      }

      eventIds.add(event.id);

      const timestamp = Date.parse(event.occurred_at);

      if (timestamp < previousTimestamp) {
        context.addIssue({
          code: 'custom',
          path: ['timeline', index, 'occurred_at'],
          message: 'Trace timeline events must be chronologically ordered.',
        });
      }

      previousTimestamp = timestamp;
    });
  });

export type TraceStatus = z.infer<typeof traceStatusSchema>;

export type TraceSummary = z.infer<typeof traceSummarySchema>;

export type TracePage = z.infer<typeof tracePageSchema>;

export type TraceComponentCounts = z.infer<typeof traceComponentCountsSchema>;

export type TraceTimelineEvent = z.infer<typeof traceTimelineEventSchema>;

export type TraceDetail = z.infer<typeof traceDetailSchema>;

function decode<T>(schema: z.ZodType<T>, value: unknown): T {
  const result = schema.safeParse(value);

  if (!result.success) {
    throw SafeApiError.fromLocal('invalid-response');
  }

  return result.data;
}

function checkPagination(page: TracePage) {
  const expectedNextOffset = page.offset + page.count;

  if (
    page.count !== page.items.length ||
    page.count > page.limit ||
    page.total < expectedNextOffset ||
    (page.has_more && (page.count === 0 || page.next_offset !== expectedNextOffset)) ||
    (!page.has_more && page.next_offset !== null)
  ) {
    throw SafeApiError.fromLocal('invalid-response');
  }
}

export function decodeTracePage(value: unknown): TracePage {
  const page = decode(tracePageSchema, value);

  checkPagination(page);
  return page;
}

export function decodeTraceDetail(value: unknown): TraceDetail {
  return decode(traceDetailSchema, value);
}
