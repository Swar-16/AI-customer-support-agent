// apps/web/src/features/knowledge/knowledge-api.ts

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult, createTransport } from '../../shared/api/transport';
import {
  createKnowledgeDocumentInputSchema,
  createKnowledgeVersionInputSchema,
  decodeArchiveKnowledgeDocumentResponse,
  decodeCreateKnowledgeDocumentResponse,
  decodeCreateKnowledgeVersionResponse,
  decodeEmbedKnowledgeVersionResponse,
  decodeKnowledgeDocumentDetail,
  decodeKnowledgeDocumentPage,
  decodeKnowledgeVersionDetail,
  decodeKnowledgeVersionPage,
  decodeProcessKnowledgeVersionResponse,
  decodePublishKnowledgeVersionResponse,
  decodeUploadKnowledgeDocumentResponse,
  decodeUploadKnowledgeVersionResponse,
  knowledgeDocumentFiltersSchema,
  knowledgeIdSchema,
  knowledgeVersionFiltersSchema,
  type ArchiveKnowledgeDocumentResponse,
  type CreateKnowledgeDocumentInput,
  type CreateKnowledgeDocumentResponse,
  type CreateKnowledgeVersionInput,
  type CreateKnowledgeVersionResponse,
  type EmbedKnowledgeVersionResponse,
  type KnowledgeDocumentDetail,
  type KnowledgeDocumentFilters,
  type KnowledgeDocumentPage,
  type KnowledgeVersionDetail,
  type KnowledgeVersionFilters,
  type KnowledgeVersionPage,
  type ProcessKnowledgeVersionResponse,
  type PublishKnowledgeVersionResponse,
  type UploadKnowledgeDocumentResponse,
  type UploadKnowledgeVersionResponse,
} from './knowledge-contract';

type Transport = ReturnType<typeof createTransport>;

export type UploadKnowledgeDocumentInput = CreateKnowledgeDocumentInput & {
  readonly file: File;
};

export interface UploadKnowledgeVersionInput {
  readonly documentId: string;
  readonly file: File;
}

const UPLOAD_TIMEOUT_MS = 120_000;
const PROCESS_TIMEOUT_MS = 120_000;
const EMBED_TIMEOUT_MS = 180_000;
const PUBLISH_TIMEOUT_MS = 60_000;

function invalidRequest<T>(): Promise<TransportResult<T>> {
  return Promise.resolve({
    ok: false,
    error: SafeApiError.fromLocal('invalid-response'),
    retryAfterMs: null,
  });
}

function requestSignal(signal: AbortSignal | undefined): { readonly signal?: AbortSignal } {
  return signal === undefined ? {} : { signal };
}

function isUsableFile(value: unknown): value is File {
  return (
    typeof File !== 'undefined' &&
    value instanceof File &&
    value.name.trim().length > 0 &&
    value.size > 0
  );
}

function requireMatchingId<T>(result: T, actualId: string, expectedId: string): T {
  if (actualId !== expectedId) {
    throw new Error('The response resource does not match the requested resource.');
  }

  return result;
}

export function createKnowledgeApi(request: Transport) {
  return {
    listDocuments(
      filters: KnowledgeDocumentFilters,
      signal?: AbortSignal,
    ): Promise<TransportResult<KnowledgeDocumentPage>> {
      const parsed = knowledgeDocumentFiltersSchema.safeParse(filters);

      if (!parsed.success) {
        return invalidRequest();
      }

      const query = new URLSearchParams({
        limit: String(parsed.data.limit),
        offset: String(parsed.data.offset),
      });

      if (parsed.data.status !== null) {
        query.set('status', parsed.data.status);
      }

      if (parsed.data.contentType !== null) {
        query.set('content_type', parsed.data.contentType);
      }

      if (parsed.data.visibility !== null) {
        query.set('visibility', parsed.data.visibility);
      }

      return request({
        path: '/v1/knowledge/documents',
        method: 'GET',
        authentication: 'bearer',
        query,
        decode: decodeKnowledgeDocumentPage,
        ...requestSignal(signal),
      });
    },

    getDocument(
      documentId: string,
      signal?: AbortSignal,
    ): Promise<TransportResult<KnowledgeDocumentDetail>> {
      const parsedId = knowledgeIdSchema.safeParse(documentId);

      if (!parsedId.success) {
        return invalidRequest();
      }

      return request({
        path: `/v1/knowledge/documents/${parsedId.data}`,
        method: 'GET',
        authentication: 'bearer',

        decode: (value) => {
          const document = decodeKnowledgeDocumentDetail(value);

          return requireMatchingId(document, document.document_id, parsedId.data);
        },

        ...requestSignal(signal),
      });
    },

    createDocument(
      input: CreateKnowledgeDocumentInput,
      signal?: AbortSignal,
    ): Promise<TransportResult<CreateKnowledgeDocumentResponse>> {
      const parsed = createKnowledgeDocumentInputSchema.safeParse(input);

      if (!parsed.success) {
        return invalidRequest();
      }

      return request({
        path: '/v1/knowledge/documents',
        method: 'POST',
        authentication: 'bearer',
        body: {
          kind: 'json',
          value: parsed.data,
        },
        decode: decodeCreateKnowledgeDocumentResponse,
        ...requestSignal(signal),
      });
    },

    uploadDocument(
      input: UploadKnowledgeDocumentInput,
      signal?: AbortSignal,
    ): Promise<TransportResult<UploadKnowledgeDocumentResponse>> {
      if (!isUsableFile(input.file)) {
        return invalidRequest();
      }

      const metadata = createKnowledgeDocumentInputSchema.safeParse({
        title: input.title,
        description: input.description,
        content_type: input.content_type,
        visibility: input.visibility,
      });

      if (!metadata.success) {
        return invalidRequest();
      }

      const form = new FormData();

      form.set('file', input.file);
      form.set('title', metadata.data.title);
      form.set('content_type', metadata.data.content_type);
      form.set('visibility', metadata.data.visibility);

      if (metadata.data.description !== null) {
        form.set('description', metadata.data.description);
      }

      return request({
        path: '/v1/knowledge/documents/upload',
        method: 'POST',
        authentication: 'bearer',
        body: {
          kind: 'multipart',
          value: form,
        },
        timeoutMs: UPLOAD_TIMEOUT_MS,

        decode: (value, context) => decodeUploadKnowledgeDocumentResponse(value, context.status),

        ...requestSignal(signal),
      });
    },

    archiveDocument(
      documentId: string,
      signal?: AbortSignal,
    ): Promise<TransportResult<ArchiveKnowledgeDocumentResponse>> {
      const parsedId = knowledgeIdSchema.safeParse(documentId);

      if (!parsedId.success) {
        return invalidRequest();
      }

      return request({
        path: `/v1/knowledge/documents/${parsedId.data}/archive`,
        method: 'POST',
        authentication: 'bearer',

        decode: (value) => {
          const response = decodeArchiveKnowledgeDocumentResponse(value);

          return requireMatchingId(response, response.document_id, parsedId.data);
        },

        ...requestSignal(signal),
      });
    },

    listVersions(
      documentId: string,
      filters: KnowledgeVersionFilters,
      signal?: AbortSignal,
    ): Promise<TransportResult<KnowledgeVersionPage>> {
      const parsedId = knowledgeIdSchema.safeParse(documentId);

      const parsedFilters = knowledgeVersionFiltersSchema.safeParse(filters);

      if (!parsedId.success || !parsedFilters.success) {
        return invalidRequest();
      }

      const query = new URLSearchParams({
        limit: String(parsedFilters.data.limit),
        offset: String(parsedFilters.data.offset),
      });

      if (parsedFilters.data.status !== null) {
        query.set('status', parsedFilters.data.status);
      }

      if (parsedFilters.data.ingestionStatus !== null) {
        query.set('ingestion_status', parsedFilters.data.ingestionStatus);
      }

      if (parsedFilters.data.sourceType !== null) {
        query.set('source_type', parsedFilters.data.sourceType);
      }

      return request({
        path: `/v1/knowledge/documents/${parsedId.data}/versions`,
        method: 'GET',
        authentication: 'bearer',
        query,

        decode: (value) => {
          const page = decodeKnowledgeVersionPage(value);

          return requireMatchingId(page, page.document_id, parsedId.data);
        },

        ...requestSignal(signal),
      });
    },

    getVersion(
      versionId: string,
      signal?: AbortSignal,
    ): Promise<TransportResult<KnowledgeVersionDetail>> {
      const parsedId = knowledgeIdSchema.safeParse(versionId);

      if (!parsedId.success) {
        return invalidRequest();
      }

      return request({
        path: `/v1/knowledge/versions/${parsedId.data}`,
        method: 'GET',
        authentication: 'bearer',

        decode: (value) => {
          const version = decodeKnowledgeVersionDetail(value);

          return requireMatchingId(version, version.version_id, parsedId.data);
        },

        ...requestSignal(signal),
      });
    },

    createVersion(
      documentId: string,
      input: CreateKnowledgeVersionInput,
      signal?: AbortSignal,
    ): Promise<TransportResult<CreateKnowledgeVersionResponse>> {
      const parsedId = knowledgeIdSchema.safeParse(documentId);

      const parsedInput = createKnowledgeVersionInputSchema.safeParse(input);

      if (!parsedId.success || !parsedInput.success) {
        return invalidRequest();
      }

      return request({
        path: `/v1/knowledge/documents/${parsedId.data}/versions`,
        method: 'POST',
        authentication: 'bearer',
        body: {
          kind: 'json',
          value: parsedInput.data,
        },

        decode: (value) => {
          const response = decodeCreateKnowledgeVersionResponse(value);

          return requireMatchingId(response, response.document_id, parsedId.data);
        },

        ...requestSignal(signal),
      });
    },

    uploadVersion(
      input: UploadKnowledgeVersionInput,
      signal?: AbortSignal,
    ): Promise<TransportResult<UploadKnowledgeVersionResponse>> {
      const parsedDocumentId = knowledgeIdSchema.safeParse(input.documentId);

      if (!parsedDocumentId.success || !isUsableFile(input.file)) {
        return invalidRequest();
      }

      const form = new FormData();

      form.set('file', input.file);

      return request({
        path: `/v1/knowledge/documents/${parsedDocumentId.data}/versions/upload`,
        method: 'POST',
        authentication: 'bearer',
        body: {
          kind: 'multipart',
          value: form,
        },
        timeoutMs: UPLOAD_TIMEOUT_MS,

        decode: (value, context) => {
          const response = decodeUploadKnowledgeVersionResponse(value, context.status);

          return requireMatchingId(response, response.document_id, parsedDocumentId.data);
        },

        ...requestSignal(signal),
      });
    },

    processVersion(
      versionId: string,
      signal?: AbortSignal,
    ): Promise<TransportResult<ProcessKnowledgeVersionResponse>> {
      const parsedId = knowledgeIdSchema.safeParse(versionId);

      if (!parsedId.success) {
        return invalidRequest();
      }

      return request({
        path: `/v1/knowledge/versions/${parsedId.data}/process`,
        method: 'POST',
        authentication: 'bearer',
        timeoutMs: PROCESS_TIMEOUT_MS,

        decode: (value) => {
          const response = decodeProcessKnowledgeVersionResponse(value);

          return requireMatchingId(response, response.version_id, parsedId.data);
        },

        ...requestSignal(signal),
      });
    },

    embedVersion(
      versionId: string,
      signal?: AbortSignal,
    ): Promise<TransportResult<EmbedKnowledgeVersionResponse>> {
      const parsedId = knowledgeIdSchema.safeParse(versionId);

      if (!parsedId.success) {
        return invalidRequest();
      }

      return request({
        path: `/v1/knowledge/versions/${parsedId.data}/embed`,
        method: 'POST',
        authentication: 'bearer',
        timeoutMs: EMBED_TIMEOUT_MS,

        decode: (value) => {
          const response = decodeEmbedKnowledgeVersionResponse(value);

          return requireMatchingId(response, response.version_id, parsedId.data);
        },

        ...requestSignal(signal),
      });
    },

    publishVersion(
      versionId: string,
      signal?: AbortSignal,
    ): Promise<TransportResult<PublishKnowledgeVersionResponse>> {
      const parsedId = knowledgeIdSchema.safeParse(versionId);

      if (!parsedId.success) {
        return invalidRequest();
      }

      return request({
        path: `/v1/knowledge/versions/${parsedId.data}/publish`,
        method: 'POST',
        authentication: 'bearer',
        timeoutMs: PUBLISH_TIMEOUT_MS,

        decode: (value) => {
          const response = decodePublishKnowledgeVersionResponse(value);

          return requireMatchingId(response, response.version_id, parsedId.data);
        },

        ...requestSignal(signal),
      });
    },
  };
}

export type KnowledgeApi = ReturnType<typeof createKnowledgeApi>;
