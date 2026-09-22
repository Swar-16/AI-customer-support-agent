// apps/web/src/features/knowledge/knowledge-contract.ts

import { z } from 'zod';

import type { components } from '../../shared/api/generated/schema';

type ApiSchemas = components['schemas'];

/* -------------------------------------------------------------------------- */
/*                                  Primitives                                */
/* -------------------------------------------------------------------------- */

export const knowledgeIdSchema = z.uuid();

export const knowledgeTimestampSchema = z.iso.datetime({
  offset: true,
});

export const knowledgeContentHashSchema = z
  .string()
  .length(64)
  .regex(/^[0-9a-f]{64}$/u, 'Expected a lowercase SHA-256 hash.');

const nonnegativeIntegerSchema = z.number().int().nonnegative();

const positiveIntegerSchema = z.number().int().positive();

const optionalNullableTimestampSchema = knowledgeTimestampSchema.nullable().default(null);

const optionalNullableStringSchema = z.string().nullable().default(null);

/* -------------------------------------------------------------------------- */
/*                                    Enums                                   */
/* -------------------------------------------------------------------------- */

export const knowledgeDocumentStatusSchema = z.enum(['active', 'archived', 'deleted']);

export const knowledgeContentTypeSchema = z.enum([
  'policy',
  'faq',
  'procedure',
  'guide',
  'reference',
  'other',
]);

export const knowledgeVisibilitySchema = z.enum(['customer', 'internal', 'both']);

export const knowledgeVersionStatusSchema = z.enum([
  'draft',
  'processing',
  'ready',
  'published',
  'superseded',
  'failed',
  'archived',
]);

export const knowledgeIngestionStatusSchema = z.enum(['pending', 'running', 'completed', 'failed']);

export const knowledgeSourceTypeSchema = z.enum([
  'markdown',
  'plain_text',
  'pdf',
  'docx',
  'html',
  'rich_text',
]);

export type KnowledgeDocumentStatus = ApiSchemas['KnowledgeDocumentStatus'];

export type KnowledgeContentType = ApiSchemas['KnowledgeContentType'];

export type KnowledgeVisibility = ApiSchemas['KnowledgeVisibility'];

export type KnowledgeVersionStatus = ApiSchemas['KnowledgeVersionStatus'];

export type KnowledgeIngestionStatus = ApiSchemas['KnowledgeIngestionStatus'];

export type KnowledgeSourceType = ApiSchemas['KnowledgeSourceType'];

/* -------------------------------------------------------------------------- */
/*                              Document schemas                              */
/* -------------------------------------------------------------------------- */

export const knowledgeDocumentSchema = z.object({
  document_id: knowledgeIdSchema,
  title: z.string().min(1),
  description: optionalNullableStringSchema,
  content_type: knowledgeContentTypeSchema,
  visibility: knowledgeVisibilitySchema,
  status: knowledgeDocumentStatusSchema,
  created_at: knowledgeTimestampSchema,
  updated_at: knowledgeTimestampSchema,
  archived_at: optionalNullableTimestampSchema,
}) satisfies z.ZodType<ApiSchemas['KnowledgeDocumentSummaryResponse']>;

export const knowledgeDocumentDetailSchema = z.object({
  document_id: knowledgeIdSchema,
  title: z.string().min(1),
  description: optionalNullableStringSchema,
  content_type: knowledgeContentTypeSchema,
  visibility: knowledgeVisibilitySchema,
  status: knowledgeDocumentStatusSchema,
  created_at: knowledgeTimestampSchema,
  updated_at: knowledgeTimestampSchema,
  archived_at: optionalNullableTimestampSchema,
  published_version_id: knowledgeIdSchema.nullable().default(null),
  version_count: nonnegativeIntegerSchema,
}) satisfies z.ZodType<ApiSchemas['KnowledgeDocumentDetailResponse']>;

/* -------------------------------------------------------------------------- */
/*                               Version schemas                              */
/* -------------------------------------------------------------------------- */

export const knowledgeVersionSchema = z.object({
  version_id: knowledgeIdSchema,
  document_id: knowledgeIdSchema,
  version_number: positiveIntegerSchema,
  source_type: knowledgeSourceTypeSchema,
  source_name: optionalNullableStringSchema,
  content_hash: knowledgeContentHashSchema,
  status: knowledgeVersionStatusSchema,
  ingestion_status: knowledgeIngestionStatusSchema,
  failure_code: z.string().max(200).nullable().default(null),
  created_at: knowledgeTimestampSchema,
  updated_at: knowledgeTimestampSchema,
  processing_started_at: optionalNullableTimestampSchema,
  processing_completed_at: optionalNullableTimestampSchema,
  ready_at: optionalNullableTimestampSchema,
  published_at: optionalNullableTimestampSchema,
  superseded_at: optionalNullableTimestampSchema,
  archived_at: optionalNullableTimestampSchema,
}) satisfies z.ZodType<ApiSchemas['KnowledgeVersionSummaryResponse']>;

export const knowledgeVersionDetailSchema = z
  .object({
    version_id: knowledgeIdSchema,
    document_id: knowledgeIdSchema,
    version_number: positiveIntegerSchema,
    source_type: knowledgeSourceTypeSchema,
    source_name: optionalNullableStringSchema,
    content_hash: knowledgeContentHashSchema,
    status: knowledgeVersionStatusSchema,
    ingestion_status: knowledgeIngestionStatusSchema,
    failure_code: z.string().max(200).nullable().default(null),
    created_at: knowledgeTimestampSchema,
    updated_at: knowledgeTimestampSchema,
    processing_started_at: optionalNullableTimestampSchema,
    processing_completed_at: optionalNullableTimestampSchema,
    ready_at: optionalNullableTimestampSchema,
    published_at: optionalNullableTimestampSchema,
    superseded_at: optionalNullableTimestampSchema,
    archived_at: optionalNullableTimestampSchema,
    document_title: z.string().min(1),
    is_current_published_version: z.boolean(),
    source_content_length: positiveIntegerSchema,

    /*
     * Persisted embedding state reported by the backend.
     * These values are authoritative for publish availability.
     */
    total_chunk_count: nonnegativeIntegerSchema,
    embedded_chunk_count: nonnegativeIntegerSchema,
    is_fully_embedded: z.boolean(),
  })
  .superRefine((version, context) => {
    if (version.embedded_chunk_count > version.total_chunk_count) {
      context.addIssue({
        code: 'custom',
        path: ['embedded_chunk_count'],
        message: 'Embedded chunk count cannot exceed total chunk count.',
      });
    }

    const expectedFullyEmbedded =
      version.total_chunk_count > 0 && version.embedded_chunk_count === version.total_chunk_count;

    if (version.is_fully_embedded !== expectedFullyEmbedded) {
      context.addIssue({
        code: 'custom',
        path: ['is_fully_embedded'],
        message: 'Embedding completion state is inconsistent with chunk counts.',
      });
    }
  }) satisfies z.ZodType<ApiSchemas['KnowledgeVersionDetailResponse']>;

/* -------------------------------------------------------------------------- */
/*                              Pagination checks                             */
/* -------------------------------------------------------------------------- */

interface PaginationShape {
  readonly count: number;
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
  readonly has_more: boolean;
  readonly next_offset?: number | null;
  readonly items: readonly unknown[];
}

function validatePagination(page: PaginationShape, context: z.RefinementCtx): void {
  if (page.count !== page.items.length) {
    context.addIssue({
      code: 'custom',
      path: ['count'],
      message: 'Page count must equal the number of returned items.',
    });
  }

  if (page.items.length > page.limit) {
    context.addIssue({
      code: 'custom',
      path: ['items'],
      message: 'A page cannot contain more items than its limit.',
    });
  }

  if (page.offset + page.count > page.total) {
    context.addIssue({
      code: 'custom',
      path: ['total'],
      message: 'Page offset and count exceed the reported total.',
    });
  }

  const expectedHasMore = page.offset + page.count < page.total;

  if (page.has_more !== expectedHasMore) {
    context.addIssue({
      code: 'custom',
      path: ['has_more'],
      message: 'The has_more value is inconsistent with pagination totals.',
    });
  }

  if (page.has_more) {
    const expectedNextOffset = page.offset + page.count;

    if (page.next_offset !== expectedNextOffset) {
      context.addIssue({
        code: 'custom',
        path: ['next_offset'],
        message: 'The next offset does not continue from the current page.',
      });
    }
  } else if (page.next_offset !== null && page.next_offset !== undefined) {
    context.addIssue({
      code: 'custom',
      path: ['next_offset'],
      message: 'A terminal page must not provide a next offset.',
    });
  }
}

/* -------------------------------------------------------------------------- */
/*                               Document page                                */
/* -------------------------------------------------------------------------- */

export const knowledgeDocumentPageSchema = z
  .object({
    items: z.array(knowledgeDocumentSchema),
    total: nonnegativeIntegerSchema,
    count: nonnegativeIntegerSchema,
    limit: z.number().int().min(1).max(200),
    offset: nonnegativeIntegerSchema,
    has_more: z.boolean(),
    next_offset: nonnegativeIntegerSchema.nullable().default(null),
  })
  .superRefine((page, context) => {
    validatePagination(page, context);

    const documentIds = new Set<string>();

    page.items.forEach((document, index) => {
      if (documentIds.has(document.document_id)) {
        context.addIssue({
          code: 'custom',
          path: ['items', index, 'document_id'],
          message: 'Document identifiers must be unique within a page.',
        });
      }

      documentIds.add(document.document_id);
    });
  }) satisfies z.ZodType<ApiSchemas['KnowledgeDocumentListResponse']>;

/* -------------------------------------------------------------------------- */
/*                                Version page                                */
/* -------------------------------------------------------------------------- */

export const knowledgeVersionPageSchema = z
  .object({
    document_id: knowledgeIdSchema,
    items: z.array(knowledgeVersionSchema),
    total: nonnegativeIntegerSchema,
    count: nonnegativeIntegerSchema,
    limit: z.number().int().min(1).max(200),
    offset: nonnegativeIntegerSchema,
    has_more: z.boolean(),
    next_offset: nonnegativeIntegerSchema.nullable().default(null),
  })
  .superRefine((page, context) => {
    validatePagination(page, context);

    const versionIds = new Set<string>();

    page.items.forEach((version, index) => {
      if (version.document_id !== page.document_id) {
        context.addIssue({
          code: 'custom',
          path: ['items', index, 'document_id'],
          message: 'Every version must belong to the requested document.',
        });
      }

      if (versionIds.has(version.version_id)) {
        context.addIssue({
          code: 'custom',
          path: ['items', index, 'version_id'],
          message: 'Version identifiers must be unique within a page.',
        });
      }

      versionIds.add(version.version_id);
    });
  }) satisfies z.ZodType<ApiSchemas['KnowledgeVersionListResponse']>;

/* -------------------------------------------------------------------------- */
/*                               Request schemas                              */
/* -------------------------------------------------------------------------- */

export const createKnowledgeDocumentInputSchema = z
  .object({
    title: z.string().trim().min(1).max(300),

    description: z.string().trim().max(2_000).nullable().default(null),

    content_type: knowledgeContentTypeSchema,

    visibility: knowledgeVisibilitySchema.default('customer'),
  })
  .strict() satisfies z.ZodType<ApiSchemas['CreateKnowledgeDocumentRequest']>;

export const createKnowledgeVersionInputSchema = z
  .object({
    source_type: knowledgeSourceTypeSchema,

    source_content: z.string().min(1).max(2_000_000),

    source_name: z.string().trim().max(500).nullable().default(null),
  })
  .strict() satisfies z.ZodType<ApiSchemas['CreateKnowledgeVersionRequest']>;

/* -------------------------------------------------------------------------- */
/*                               Filter schemas                               */
/* -------------------------------------------------------------------------- */

export const knowledgeDocumentFiltersSchema = z
  .object({
    status: knowledgeDocumentStatusSchema.nullable(),

    contentType: knowledgeContentTypeSchema.nullable(),

    visibility: knowledgeVisibilitySchema.nullable(),

    limit: z.number().int().min(1).max(200),

    offset: nonnegativeIntegerSchema,
  })
  .strict();

export const knowledgeVersionFiltersSchema = z
  .object({
    status: knowledgeVersionStatusSchema.nullable(),

    ingestionStatus: knowledgeIngestionStatusSchema.nullable(),

    sourceType: knowledgeSourceTypeSchema.nullable(),

    limit: z.number().int().min(1).max(200),

    offset: nonnegativeIntegerSchema,
  })
  .strict();

/* -------------------------------------------------------------------------- */
/*                             Mutation responses                             */
/* -------------------------------------------------------------------------- */

export const createKnowledgeDocumentResponseSchema = z.object({
  document_id: knowledgeIdSchema,
  created_at: knowledgeTimestampSchema,
}) satisfies z.ZodType<ApiSchemas['CreateKnowledgeDocumentResponse']>;

export const createKnowledgeVersionResponseSchema = z.object({
  document_id: knowledgeIdSchema,
  version_id: knowledgeIdSchema,
  version_number: positiveIntegerSchema,
  content_hash: knowledgeContentHashSchema,
  created_at: knowledgeTimestampSchema,
}) satisfies z.ZodType<ApiSchemas['CreateKnowledgeVersionResponse']>;

export const uploadKnowledgeDocumentResponseSchema = z.object({
  document_id: knowledgeIdSchema,
  version_id: knowledgeIdSchema,
  version_number: positiveIntegerSchema,
  filename: z.string().min(1).max(255),
  source_type: knowledgeSourceTypeSchema,
  content_hash: knowledgeContentHashSchema,
  uploaded_size_bytes: positiveIntegerSchema,
  document_status: knowledgeDocumentStatusSchema,
  version_status: knowledgeVersionStatusSchema,
  ingestion_status: knowledgeIngestionStatusSchema,
  created_at: knowledgeTimestampSchema,
}) satisfies z.ZodType<ApiSchemas['UploadKnowledgeDocumentResponse']>;

export const uploadKnowledgeVersionResponseSchema = z.object({
  document_id: knowledgeIdSchema,
  version_id: knowledgeIdSchema,
  version_number: positiveIntegerSchema,
  source_type: knowledgeSourceTypeSchema,
  source_name: z.string().max(500).nullable().default(null),
  content_hash: knowledgeContentHashSchema,
  uploaded_size_bytes: positiveIntegerSchema,
  status: knowledgeVersionStatusSchema,
  ingestion_status: knowledgeIngestionStatusSchema,
  created: z.boolean(),
  created_at: knowledgeTimestampSchema,
  updated_at: knowledgeTimestampSchema,
}) satisfies z.ZodType<ApiSchemas['UploadKnowledgeVersionResponse']>;

export const archiveKnowledgeDocumentResponseSchema = z.object({
  document_id: knowledgeIdSchema,
  status: knowledgeDocumentStatusSchema,
  archived_at: knowledgeTimestampSchema,
  superseded_version_id: knowledgeIdSchema.nullable().default(null),
}) satisfies z.ZodType<ApiSchemas['ArchiveKnowledgeDocumentResponse']>;

export const processKnowledgeVersionResponseSchema = z.object({
  version_id: knowledgeIdSchema,
  document_id: knowledgeIdSchema,
  chunk_count: positiveIntegerSchema,
  parser_identity: z.string().min(1).max(300),
  normalizer_identity: z.string().min(1).max(300),
  chunker_identity: z.string().min(1).max(300),
  version_status: knowledgeVersionStatusSchema,
  ingestion_status: knowledgeIngestionStatusSchema,
}) satisfies z.ZodType<ApiSchemas['ProcessKnowledgeVersionResponse']>;

export const embedKnowledgeVersionResponseSchema = z
  .object({
    version_id: knowledgeIdSchema,
    document_id: knowledgeIdSchema,
    total_chunks: positiveIntegerSchema,
    existing_count: nonnegativeIntegerSchema,
    created_count: nonnegativeIntegerSchema,
    provider_identity: z.string().min(1).max(300),
    input_strategy_identity: z.string().min(1).max(300),
  })
  .superRefine((result, context) => {
    if (result.existing_count + result.created_count !== result.total_chunks) {
      context.addIssue({
        code: 'custom',
        path: ['total_chunks'],
        message: 'Existing and newly created embeddings must equal the total chunk count.',
      });
    }
  }) satisfies z.ZodType<ApiSchemas['EmbedKnowledgeVersionResponse']>;

export const publishKnowledgeVersionResponseSchema = z.object({
  version_id: knowledgeIdSchema,
  document_id: knowledgeIdSchema,
  version_number: positiveIntegerSchema,
  status: knowledgeVersionStatusSchema,
  published_at: knowledgeTimestampSchema,
  superseded_version_id: knowledgeIdSchema.nullable().default(null),
}) satisfies z.ZodType<ApiSchemas['PublishKnowledgeVersionResponse']>;

/* -------------------------------------------------------------------------- */
/*                               Exported types                               */
/* -------------------------------------------------------------------------- */

export type KnowledgeDocument = z.infer<typeof knowledgeDocumentSchema>;

export type KnowledgeDocumentDetail = z.infer<typeof knowledgeDocumentDetailSchema>;

export type KnowledgeVersion = z.infer<typeof knowledgeVersionSchema>;

export type KnowledgeVersionDetail = z.infer<typeof knowledgeVersionDetailSchema>;

export type KnowledgeDocumentPage = z.infer<typeof knowledgeDocumentPageSchema>;

export type KnowledgeVersionPage = z.infer<typeof knowledgeVersionPageSchema>;

export type KnowledgeDocumentFilters = z.infer<typeof knowledgeDocumentFiltersSchema>;

export type KnowledgeVersionFilters = z.infer<typeof knowledgeVersionFiltersSchema>;

export type CreateKnowledgeDocumentInput = z.infer<typeof createKnowledgeDocumentInputSchema>;

export type CreateKnowledgeVersionInput = z.infer<typeof createKnowledgeVersionInputSchema>;

export type CreateKnowledgeDocumentResponse = z.infer<typeof createKnowledgeDocumentResponseSchema>;

export type CreateKnowledgeVersionResponse = z.infer<typeof createKnowledgeVersionResponseSchema>;

export type UploadKnowledgeDocumentResponse = z.infer<typeof uploadKnowledgeDocumentResponseSchema>;

export type UploadKnowledgeVersionResponse = z.infer<typeof uploadKnowledgeVersionResponseSchema>;

export type ArchiveKnowledgeDocumentResponse = z.infer<
  typeof archiveKnowledgeDocumentResponseSchema
>;

export type ProcessKnowledgeVersionResponse = z.infer<typeof processKnowledgeVersionResponseSchema>;

export type EmbedKnowledgeVersionResponse = z.infer<typeof embedKnowledgeVersionResponseSchema>;

export type PublishKnowledgeVersionResponse = z.infer<typeof publishKnowledgeVersionResponseSchema>;

/* -------------------------------------------------------------------------- */
/*                                  Decoders                                  */
/* -------------------------------------------------------------------------- */

export function decodeKnowledgeDocumentPage(value: unknown): KnowledgeDocumentPage {
  return knowledgeDocumentPageSchema.parse(value);
}

export function decodeKnowledgeDocumentDetail(value: unknown): KnowledgeDocumentDetail {
  return knowledgeDocumentDetailSchema.parse(value);
}

export function decodeKnowledgeVersionPage(value: unknown): KnowledgeVersionPage {
  return knowledgeVersionPageSchema.parse(value);
}

export function decodeKnowledgeVersionDetail(value: unknown): KnowledgeVersionDetail {
  return knowledgeVersionDetailSchema.parse(value);
}

export function decodeCreateKnowledgeDocumentResponse(
  value: unknown,
): CreateKnowledgeDocumentResponse {
  return createKnowledgeDocumentResponseSchema.parse(value);
}

export function decodeCreateKnowledgeVersionResponse(
  value: unknown,
): CreateKnowledgeVersionResponse {
  return createKnowledgeVersionResponseSchema.parse(value);
}

export function decodeUploadKnowledgeDocumentResponse(
  value: unknown,
  httpStatus: number,
): UploadKnowledgeDocumentResponse {
  if (httpStatus !== 201) {
    throw new Error('Unexpected knowledge-document upload status.');
  }

  return uploadKnowledgeDocumentResponseSchema.parse(value);
}

export function decodeUploadKnowledgeVersionResponse(
  value: unknown,
  httpStatus: number,
): UploadKnowledgeVersionResponse {
  if (httpStatus !== 200 && httpStatus !== 201) {
    throw new Error('Unexpected knowledge-version upload status.');
  }

  const response = uploadKnowledgeVersionResponseSchema.parse(value);

  const expectedCreated = httpStatus === 201;

  if (response.created !== expectedCreated) {
    throw new Error('Knowledge-version upload status and created flag are inconsistent.');
  }

  return response;
}

export function decodeArchiveKnowledgeDocumentResponse(
  value: unknown,
): ArchiveKnowledgeDocumentResponse {
  return archiveKnowledgeDocumentResponseSchema.parse(value);
}

export function decodeProcessKnowledgeVersionResponse(
  value: unknown,
): ProcessKnowledgeVersionResponse {
  return processKnowledgeVersionResponseSchema.parse(value);
}

export function decodeEmbedKnowledgeVersionResponse(value: unknown): EmbedKnowledgeVersionResponse {
  return embedKnowledgeVersionResponseSchema.parse(value);
}

export function decodePublishKnowledgeVersionResponse(
  value: unknown,
): PublishKnowledgeVersionResponse {
  return publishKnowledgeVersionResponseSchema.parse(value);
}
