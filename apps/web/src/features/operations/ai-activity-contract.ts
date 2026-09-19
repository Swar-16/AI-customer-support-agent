// apps/web/src/features/operations/ai-activity-contract.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';

export const analyticsBucketSchema = z.enum(['hour', 'day', 'week']);

const timestampSchema = z.iso.datetime({
  offset: true,
});

const nonnegativeIntegerSchema = z.number().int().nonnegative();

const decimalStringSchema = z.string().regex(/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/u);

const nullableDecimalStringSchema = decimalStringSchema.nullable();

export const analyticsWindowSchema = z
  .object({
    started_at: timestampSchema,
    ended_at: timestampSchema,
    bucket: analyticsBucketSchema,
  })
  .strict()
  .superRefine((window, context) => {
    if (Date.parse(window.started_at) >= Date.parse(window.ended_at)) {
      context.addIssue({
        code: 'custom',
        path: ['ended_at'],
        message: 'Analytics window end must be later than its start.',
      });
    }
  });

export const analyticsMetadataSchema = z
  .object({
    window: analyticsWindowSchema,
    generated_at: timestampSchema,
  })
  .strict();

export const analyticsDurationSummarySchema = z
  .object({
    sample_count: nonnegativeIntegerSchema,
    average_ms: nullableDecimalStringSchema.default(null),
    p50_ms: nullableDecimalStringSchema.default(null),
    p95_ms: nullableDecimalStringSchema.default(null),
  })
  .strict();

export const analyticsCategoryCountSchema = z
  .object({
    category: z.string().trim().min(1),
    count: nonnegativeIntegerSchema,
  })
  .strict();

export const aiAnalyticsPointSchema = z
  .object({
    bucket_started_at: timestampSchema,

    runs: nonnegativeIntegerSchema,
    successful_runs: nonnegativeIntegerSchema,
    failed_runs: nonnegativeIntegerSchema,
    cancelled_runs: nonnegativeIntegerSchema,

    llm_calls: nonnegativeIntegerSchema,
    successful_llm_calls: nonnegativeIntegerSchema,
    failed_llm_calls: nonnegativeIntegerSchema,
    timed_out_llm_calls: nonnegativeIntegerSchema,

    input_tokens: nonnegativeIntegerSchema,
    output_tokens: nonnegativeIntegerSchema,
    cached_input_tokens: nonnegativeIntegerSchema,
    estimated_cost_usd: decimalStringSchema,

    retrieval_runs: nonnegativeIntegerSchema,
    failed_retrieval_runs: nonnegativeIntegerSchema,
    timed_out_retrieval_runs: nonnegativeIntegerSchema,
    zero_result_retrievals: nonnegativeIntegerSchema,

    reranker_calls: nonnegativeIntegerSchema,
    failed_reranker_calls: nonnegativeIntegerSchema,
    timed_out_reranker_calls: nonnegativeIntegerSchema,

    embedding_calls: nonnegativeIntegerSchema,
    failed_embedding_calls: nonnegativeIntegerSchema,
    timed_out_embedding_calls: nonnegativeIntegerSchema,
  })
  .strict();

const categoryDistributionSchema = z.array(analyticsCategoryCountSchema);

export const aiAnalyticsSchema = z
  .object({
    metadata: analyticsMetadataSchema,

    total_runs: nonnegativeIntegerSchema,
    running_runs: nonnegativeIntegerSchema,
    successful_runs: nonnegativeIntegerSchema,
    failed_runs: nonnegativeIntegerSchema,
    cancelled_runs: nonnegativeIntegerSchema,
    success_rate: nullableDecimalStringSchema.default(null),
    run_duration: analyticsDurationSummarySchema,

    total_llm_calls: nonnegativeIntegerSchema,
    started_llm_calls: nonnegativeIntegerSchema,
    successful_llm_calls: nonnegativeIntegerSchema,
    failed_llm_calls: nonnegativeIntegerSchema,
    timed_out_llm_calls: nonnegativeIntegerSchema,
    llm_call_duration: analyticsDurationSummarySchema,

    input_tokens: nonnegativeIntegerSchema,
    output_tokens: nonnegativeIntegerSchema,
    cached_input_tokens: nonnegativeIntegerSchema,
    estimated_cost_usd: decimalStringSchema,

    retrieval_runs: nonnegativeIntegerSchema,
    started_retrieval_runs: nonnegativeIntegerSchema,
    successful_retrieval_runs: nonnegativeIntegerSchema,
    failed_retrieval_runs: nonnegativeIntegerSchema,
    timed_out_retrieval_runs: nonnegativeIntegerSchema,
    zero_result_retrievals: nonnegativeIntegerSchema,
    zero_result_rate: nullableDecimalStringSchema.default(null),
    average_retrieval_result_count: nullableDecimalStringSchema.default(null),
    retrieval_duration: analyticsDurationSummarySchema,

    reranker_calls: nonnegativeIntegerSchema,
    started_reranker_calls: nonnegativeIntegerSchema,
    successful_reranker_calls: nonnegativeIntegerSchema,
    failed_reranker_calls: nonnegativeIntegerSchema,
    timed_out_reranker_calls: nonnegativeIntegerSchema,
    reranker_duration: analyticsDurationSummarySchema,

    embedding_calls: nonnegativeIntegerSchema,
    started_embedding_calls: nonnegativeIntegerSchema,
    successful_embedding_calls: nonnegativeIntegerSchema,
    failed_embedding_calls: nonnegativeIntegerSchema,
    timed_out_embedding_calls: nonnegativeIntegerSchema,
    embedding_duration: analyticsDurationSummarySchema,

    intent_distribution: categoryDistributionSchema,
    decision_distribution: categoryDistributionSchema,
    decision_reason_distribution: categoryDistributionSchema,

    guardrail_event_distribution: categoryDistributionSchema,
    guardrail_error_code_distribution: categoryDistributionSchema,

    llm_provider_distribution: categoryDistributionSchema,
    llm_model_distribution: categoryDistributionSchema,
    llm_error_code_distribution: categoryDistributionSchema,

    retrieval_error_code_distribution: categoryDistributionSchema,

    reranker_provider_distribution: categoryDistributionSchema,
    reranker_model_distribution: categoryDistributionSchema,
    reranker_error_code_distribution: categoryDistributionSchema,

    embedding_provider_distribution: categoryDistributionSchema,
    embedding_model_distribution: categoryDistributionSchema,
    embedding_error_code_distribution: categoryDistributionSchema,

    timeline: z.array(aiAnalyticsPointSchema),
  })
  .strict();

export type AnalyticsBucket = z.infer<typeof analyticsBucketSchema>;
export type AnalyticsWindow = z.infer<typeof analyticsWindowSchema>;
export type AnalyticsDurationSummary = z.infer<typeof analyticsDurationSummarySchema>;
export type AnalyticsCategoryCount = z.infer<typeof analyticsCategoryCountSchema>;
export type AIAnalyticsPoint = z.infer<typeof aiAnalyticsPointSchema>;
export type AIAnalytics = z.infer<typeof aiAnalyticsSchema>;
export type AnalyticsMetadata = z.infer<typeof analyticsMetadataSchema>;

export function decodeAIAnalytics(value: unknown): AIAnalytics {
  const result = aiAnalyticsSchema.safeParse(value);

  if (!result.success) {
    throw SafeApiError.fromLocal('invalid-response');
  }

  return result.data;
}
