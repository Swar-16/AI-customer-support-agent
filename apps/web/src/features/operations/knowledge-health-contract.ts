// apps/web/src/features/operations/knowledge-health-contract.ts
import { z } from 'zod';

import { SafeApiError } from '../../shared/api/safe-error';
import {
  analyticsCategoryCountSchema,
  analyticsDurationSummarySchema,
  analyticsMetadataSchema,
  type AnalyticsCategoryCount,
  type AnalyticsDurationSummary,
  type AnalyticsMetadata,
} from './ai-activity-contract';

const timestampSchema = z.iso.datetime({
  offset: true,
});

const nonnegativeIntegerSchema = z.number().int().nonnegative();

const decimalStringSchema = z.string().regex(/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/u);

export const knowledgeHealthPointSchema = z
  .object({
    bucket_started_at: timestampSchema,
    versions_created: nonnegativeIntegerSchema,
    processing_completed: nonnegativeIntegerSchema,
    processing_failed: nonnegativeIntegerSchema,
  })
  .strict();

export const knowledgeHealthSchema = z
  .object({
    metadata: analyticsMetadataSchema,
    snapshot_measured_at: timestampSchema,

    total_documents: nonnegativeIntegerSchema,
    total_versions: nonnegativeIntegerSchema,
    total_chunks: nonnegativeIntegerSchema,
    total_embeddings: nonnegativeIntegerSchema,

    versions_without_chunks: nonnegativeIntegerSchema,
    versions_missing_embeddings: nonnegativeIntegerSchema,
    processing_backlog: nonnegativeIntegerSchema,

    embedding_coverage_rate: decimalStringSchema.nullable().default(null),

    processing_duration: analyticsDurationSummarySchema,

    document_status_distribution: z.array(analyticsCategoryCountSchema),

    document_content_type_distribution: z.array(analyticsCategoryCountSchema),

    document_visibility_distribution: z.array(analyticsCategoryCountSchema),

    version_status_distribution: z.array(analyticsCategoryCountSchema),

    ingestion_status_distribution: z.array(analyticsCategoryCountSchema),

    failure_code_distribution: z.array(analyticsCategoryCountSchema),

    timeline: z.array(knowledgeHealthPointSchema),
  })
  .strict()
  .superRefine((health, context) => {
    if (health.versions_without_chunks > health.total_versions) {
      context.addIssue({
        code: 'custom',
        path: ['versions_without_chunks'],
        message: 'Versions without chunks cannot exceed total versions.',
      });
    }

    if (health.versions_missing_embeddings > health.total_versions) {
      context.addIssue({
        code: 'custom',
        path: ['versions_missing_embeddings'],
        message: 'Versions missing embeddings cannot exceed total versions.',
      });
    }

    if (health.embedding_coverage_rate !== null) {
      const coverage = Number(health.embedding_coverage_rate);

      if (!Number.isFinite(coverage) || coverage < 0 || coverage > 1) {
        context.addIssue({
          code: 'custom',
          path: ['embedding_coverage_rate'],
          message: 'Embedding coverage rate must be between zero and one.',
        });
      }
    }

    let previousTimestamp = Number.NEGATIVE_INFINITY;

    health.timeline.forEach((point, index) => {
      const timestamp = Date.parse(point.bucket_started_at);

      if (timestamp < previousTimestamp) {
        context.addIssue({
          code: 'custom',
          path: ['timeline', index, 'bucket_started_at'],
          message: 'Knowledge health timeline must be chronologically ordered.',
        });
      }

      previousTimestamp = timestamp;
    });
  });

export type KnowledgeHealthPoint = z.infer<typeof knowledgeHealthPointSchema>;

export type KnowledgeHealth = z.infer<typeof knowledgeHealthSchema>;

export type { AnalyticsCategoryCount, AnalyticsDurationSummary, AnalyticsMetadata };

export function decodeKnowledgeHealth(value: unknown): KnowledgeHealth {
  const result = knowledgeHealthSchema.safeParse(value);

  if (!result.success) {
    throw SafeApiError.fromLocal('invalid-response');
  }

  return result.data;
}
