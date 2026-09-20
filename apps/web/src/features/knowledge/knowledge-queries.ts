// apps/web/src/features/knowledge/knowledge-queries.ts

import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import { useApiTransport } from '../../shared/api/transport-context';
import { useSession } from '../../shared/auth/session-context';
import {
  createKnowledgeApi,
  type KnowledgeApi,
  type UploadKnowledgeDocumentInput,
  type UploadKnowledgeVersionInput,
} from './knowledge-api';
import type {
  ArchiveKnowledgeDocumentResponse,
  CreateKnowledgeDocumentInput,
  CreateKnowledgeDocumentResponse,
  CreateKnowledgeVersionInput,
  CreateKnowledgeVersionResponse,
  EmbedKnowledgeVersionResponse,
  KnowledgeDocumentDetail,
  KnowledgeDocumentFilters,
  KnowledgeDocumentPage,
  KnowledgeVersionDetail,
  KnowledgeVersionFilters,
  KnowledgeVersionPage,
  ProcessKnowledgeVersionResponse,
  PublishKnowledgeVersionResponse,
  UploadKnowledgeDocumentResponse,
  UploadKnowledgeVersionResponse,
} from './knowledge-contract';

/* -------------------------------------------------------------------------- */
/*                                 Query keys                                 */
/* -------------------------------------------------------------------------- */

export const knowledgeKeys = {
  root: (adminId: string | null) => ['knowledge', adminId] as const,

  documents: (adminId: string | null) => [...knowledgeKeys.root(adminId), 'documents'] as const,

  documentLists: (adminId: string | null) => [...knowledgeKeys.documents(adminId), 'list'] as const,

  documentList: (adminId: string | null, filters: KnowledgeDocumentFilters) =>
    [
      ...knowledgeKeys.documentLists(adminId),
      {
        status: filters.status,
        contentType: filters.contentType,
        visibility: filters.visibility,
        limit: filters.limit,
        offset: filters.offset,
      },
    ] as const,

  documentDetails: (adminId: string | null) =>
    [...knowledgeKeys.documents(adminId), 'detail'] as const,

  document: (adminId: string | null, documentId: string | null) =>
    [...knowledgeKeys.documentDetails(adminId), documentId] as const,

  versions: (adminId: string | null, documentId: string | null) =>
    [...knowledgeKeys.document(adminId, documentId), 'versions'] as const,

  versionList: (
    adminId: string | null,
    documentId: string | null,
    filters: KnowledgeVersionFilters,
  ) =>
    [
      ...knowledgeKeys.versions(adminId, documentId),
      'list',
      {
        status: filters.status,
        ingestionStatus: filters.ingestionStatus,
        sourceType: filters.sourceType,
        limit: filters.limit,
        offset: filters.offset,
      },
    ] as const,

  versionDetails: (adminId: string | null) =>
    [...knowledgeKeys.root(adminId), 'version-detail'] as const,

  version: (adminId: string | null, versionId: string | null) =>
    [...knowledgeKeys.versionDetails(adminId), versionId] as const,
};

/*
 * This must match the key root used by the existing
 * Operations Knowledge Health query.
 */
const knowledgeHealthKey = (adminId: string | null) =>
  ['operations', adminId, 'knowledge-health'] as const;

/* -------------------------------------------------------------------------- */
/*                              Shared utilities                              */
/* -------------------------------------------------------------------------- */

function unwrapTransportResult<T>(result: TransportResult<T>): T {
  if (!result.ok) {
    throw result.error;
  }

  return result.data;
}

function requireAdminId(adminId: string | null): string {
  if (adminId === null) {
    throw SafeApiError.fromHttp(403, null);
  }

  return adminId;
}

function isUnconfirmedMutationError(error: SafeApiError): boolean {
  return error.kind === 'network' || error.kind === 'timeout';
}

function useAdminId(): string | null {
  const session = useSession();

  if (
    session.phase !== 'authenticated' ||
    session.user === null ||
    session.user.status !== 'active' ||
    session.user.role !== 'admin'
  ) {
    return null;
  }

  return session.user.id;
}

export function useKnowledgeApi(): KnowledgeApi {
  const transport = useApiTransport();

  return useMemo(() => createKnowledgeApi(transport), [transport]);
}

/* -------------------------------------------------------------------------- */
/*                                  Queries                                   */
/* -------------------------------------------------------------------------- */

export function useKnowledgeDocuments(filters: KnowledgeDocumentFilters) {
  const api = useKnowledgeApi();
  const adminId = useAdminId();

  return useQuery<KnowledgeDocumentPage, SafeApiError>({
    queryKey: knowledgeKeys.documentList(adminId, filters),

    enabled: adminId !== null,
    staleTime: 15_000,
    retry: false,

    /*
     * Preserve the previous page while a new filter/page
     * request is loading.
     */
    placeholderData: (previous) => previous,

    queryFn: async ({ signal }) => {
      requireAdminId(adminId);

      const result = await api.listDocuments(filters, signal);

      return unwrapTransportResult(result);
    },
  });
}

export function useKnowledgeDocument(documentId: string | null) {
  const api = useKnowledgeApi();
  const adminId = useAdminId();

  return useQuery<KnowledgeDocumentDetail, SafeApiError>({
    queryKey: knowledgeKeys.document(adminId, documentId),

    enabled: adminId !== null && documentId !== null,

    staleTime: 15_000,
    retry: false,

    queryFn: async ({ signal }) => {
      requireAdminId(adminId);

      if (documentId === null) {
        throw SafeApiError.fromLocal('invalid-response');
      }

      const result = await api.getDocument(documentId, signal);

      return unwrapTransportResult(result);
    },
  });
}

export function useKnowledgeVersions(documentId: string | null, filters: KnowledgeVersionFilters) {
  const api = useKnowledgeApi();
  const adminId = useAdminId();

  return useQuery<KnowledgeVersionPage, SafeApiError>({
    queryKey: knowledgeKeys.versionList(adminId, documentId, filters),

    enabled: adminId !== null && documentId !== null,

    staleTime: 10_000,
    retry: false,
    placeholderData: (previous) => previous,

    queryFn: async ({ signal }) => {
      requireAdminId(adminId);

      if (documentId === null) {
        throw SafeApiError.fromLocal('invalid-response');
      }

      const result = await api.listVersions(documentId, filters, signal);

      return unwrapTransportResult(result);
    },

    /*
     * Poll only while the returned page contains a
     * genuinely active processing operation.
     */
    refetchInterval: (query) => {
      const page = query.state.data;

      const processing =
        page?.items.some(
          (version) => version.status === 'processing' || version.ingestion_status === 'running',
        ) ?? false;

      return processing ? 2_000 : false;
    },
  });
}

export function useKnowledgeVersion(versionId: string | null) {
  const api = useKnowledgeApi();
  const adminId = useAdminId();

  return useQuery<KnowledgeVersionDetail, SafeApiError>({
    queryKey: knowledgeKeys.version(adminId, versionId),

    enabled: adminId !== null && versionId !== null,

    staleTime: 10_000,
    retry: false,

    queryFn: async ({ signal }) => {
      requireAdminId(adminId);

      if (versionId === null) {
        throw SafeApiError.fromLocal('invalid-response');
      }

      const result = await api.getVersion(versionId, signal);

      return unwrapTransportResult(result);
    },

    refetchInterval: (query) => {
      const version = query.state.data;

      const processing =
        version?.status === 'processing' || version?.ingestion_status === 'running';

      return processing ? 2_000 : false;
    },
  });
}

/* -------------------------------------------------------------------------- */
/*                           Query invalidation                               */
/* -------------------------------------------------------------------------- */

function useKnowledgeInvalidation() {
  const queryClient = useQueryClient();
  const adminId = useAdminId();

  async function invalidateDocumentLists() {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: knowledgeKeys.documentLists(adminId),
      }),

      queryClient.invalidateQueries({
        queryKey: knowledgeHealthKey(adminId),
      }),
    ]);
  }

  async function invalidateDocument(documentId: string) {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: knowledgeKeys.documentLists(adminId),
      }),

      queryClient.invalidateQueries({
        queryKey: knowledgeKeys.document(adminId, documentId),
      }),

      queryClient.invalidateQueries({
        queryKey: knowledgeKeys.versions(adminId, documentId),
      }),

      queryClient.invalidateQueries({
        queryKey: knowledgeHealthKey(adminId),
      }),
    ]);
  }

  async function invalidateVersion(documentId: string, versionId: string) {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: knowledgeKeys.documentLists(adminId),
      }),

      queryClient.invalidateQueries({
        queryKey: knowledgeKeys.document(adminId, documentId),
      }),

      queryClient.invalidateQueries({
        queryKey: knowledgeKeys.versions(adminId, documentId),
      }),

      queryClient.invalidateQueries({
        queryKey: knowledgeKeys.version(adminId, versionId),
      }),

      queryClient.invalidateQueries({
        queryKey: knowledgeHealthKey(adminId),
      }),
    ]);
  }

  return {
    adminId,
    invalidateDocumentLists,
    invalidateDocument,
    invalidateVersion,
  };
}

/* -------------------------------------------------------------------------- */
/*                            Document mutations                              */
/* -------------------------------------------------------------------------- */

export function useCreateKnowledgeDocument() {
  const api = useKnowledgeApi();
  const invalidation = useKnowledgeInvalidation();

  return useMutation<CreateKnowledgeDocumentResponse, SafeApiError, CreateKnowledgeDocumentInput>({
    mutationKey: ['knowledge', invalidation.adminId, 'create-document'],

    retry: false,

    mutationFn: async (input) => {
      requireAdminId(invalidation.adminId);

      const result = await api.createDocument(input);

      return unwrapTransportResult(result);
    },

    onSuccess: async (response) => {
      await invalidation.invalidateDocument(response.document_id);
    },

    onError: async (error) => {
      if (isUnconfirmedMutationError(error)) {
        await invalidation.invalidateDocumentLists();
      }
    },
  });
}

export function useUploadKnowledgeDocument() {
  const api = useKnowledgeApi();
  const invalidation = useKnowledgeInvalidation();

  return useMutation<UploadKnowledgeDocumentResponse, SafeApiError, UploadKnowledgeDocumentInput>({
    mutationKey: ['knowledge', invalidation.adminId, 'upload-document'],

    retry: false,

    mutationFn: async (input) => {
      requireAdminId(invalidation.adminId);

      const result = await api.uploadDocument(input);

      return unwrapTransportResult(result);
    },

    onSuccess: async (response) => {
      await invalidation.invalidateDocument(response.document_id);
    },

    onError: async (error) => {
      if (isUnconfirmedMutationError(error)) {
        await invalidation.invalidateDocumentLists();
      }
    },
  });
}

export function useArchiveKnowledgeDocument() {
  const api = useKnowledgeApi();
  const invalidation = useKnowledgeInvalidation();

  return useMutation<ArchiveKnowledgeDocumentResponse, SafeApiError, string>({
    mutationKey: ['knowledge', invalidation.adminId, 'archive-document'],

    retry: false,

    mutationFn: async (documentId) => {
      requireAdminId(invalidation.adminId);

      const result = await api.archiveDocument(documentId);

      return unwrapTransportResult(result);
    },

    onSuccess: async (response) => {
      await invalidation.invalidateDocument(response.document_id);
    },

    onError: async (error, documentId) => {
      if (error.status === 409 || isUnconfirmedMutationError(error)) {
        await invalidation.invalidateDocument(documentId);
      }
    },
  });
}

/* -------------------------------------------------------------------------- */
/*                             Version mutations                              */
/* -------------------------------------------------------------------------- */

interface CreateKnowledgeVersionVariables {
  readonly documentId: string;
  readonly input: CreateKnowledgeVersionInput;
}

export function useCreateKnowledgeVersion() {
  const api = useKnowledgeApi();
  const invalidation = useKnowledgeInvalidation();

  return useMutation<CreateKnowledgeVersionResponse, SafeApiError, CreateKnowledgeVersionVariables>(
    {
      mutationKey: ['knowledge', invalidation.adminId, 'create-version'],

      retry: false,

      mutationFn: async ({ documentId, input }) => {
        requireAdminId(invalidation.adminId);

        const result = await api.createVersion(documentId, input);

        return unwrapTransportResult(result);
      },

      onSuccess: async (response) => {
        await invalidation.invalidateVersion(response.document_id, response.version_id);
      },

      onError: async (error, variables) => {
        if (error.status === 409 || isUnconfirmedMutationError(error)) {
          await invalidation.invalidateDocument(variables.documentId);
        }
      },
    },
  );
}

export function useUploadKnowledgeVersion() {
  const api = useKnowledgeApi();
  const invalidation = useKnowledgeInvalidation();

  return useMutation<UploadKnowledgeVersionResponse, SafeApiError, UploadKnowledgeVersionInput>({
    mutationKey: ['knowledge', invalidation.adminId, 'upload-version'],

    retry: false,

    mutationFn: async (input) => {
      requireAdminId(invalidation.adminId);

      const result = await api.uploadVersion(input);

      return unwrapTransportResult(result);
    },

    onSuccess: async (response) => {
      await invalidation.invalidateVersion(response.document_id, response.version_id);
    },

    onError: async (error, variables) => {
      if (error.status === 409 || isUnconfirmedMutationError(error)) {
        await invalidation.invalidateDocument(variables.documentId);
      }
    },
  });
}

/* -------------------------------------------------------------------------- */
/*                          Lifecycle mutations                               */
/* -------------------------------------------------------------------------- */

interface VersionLifecycleVariables {
  readonly documentId: string;
  readonly versionId: string;
}

interface VersionLifecycleResult {
  readonly document_id: string;
  readonly version_id: string;
}

type VersionLifecycleOperation<Result extends VersionLifecycleResult> = (
  api: KnowledgeApi,
  versionId: string,
) => Promise<TransportResult<Result>>;

function useVersionLifecycleMutation<Result extends VersionLifecycleResult>(
  action: 'process' | 'embed' | 'publish',
  operation: VersionLifecycleOperation<Result>,
) {
  const api = useKnowledgeApi();
  const invalidation = useKnowledgeInvalidation();

  return useMutation<Result, SafeApiError, VersionLifecycleVariables>({
    mutationKey: ['knowledge', invalidation.adminId, action],

    retry: false,

    mutationFn: async ({ versionId }) => {
      requireAdminId(invalidation.adminId);

      const result = await operation(api, versionId);

      return unwrapTransportResult(result);
    },

    onSuccess: async (response) => {
      await invalidation.invalidateVersion(response.document_id, response.version_id);
    },

    onError: async (error, variables) => {
      if (error.status === 409 || isUnconfirmedMutationError(error)) {
        /*
         * The server may have completed the operation even
         * though the client did not receive confirmation.
         * Refetch current state without resending.
         */
        await invalidation.invalidateVersion(variables.documentId, variables.versionId);
      }
    },
  });
}

export function useProcessKnowledgeVersion() {
  return useVersionLifecycleMutation<ProcessKnowledgeVersionResponse>('process', (api, versionId) =>
    api.processVersion(versionId),
  );
}

export function useEmbedKnowledgeVersion() {
  return useVersionLifecycleMutation<EmbedKnowledgeVersionResponse>('embed', (api, versionId) =>
    api.embedVersion(versionId),
  );
}

export function usePublishKnowledgeVersion() {
  return useVersionLifecycleMutation<PublishKnowledgeVersionResponse>('publish', (api, versionId) =>
    api.publishVersion(versionId),
  );
}
