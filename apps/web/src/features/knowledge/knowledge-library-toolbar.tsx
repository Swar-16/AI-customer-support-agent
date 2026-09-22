// apps/web/src/features/knowledge/knowledge-library-toolbar.tsx

import { FilePlus2, Filter, RefreshCw, Upload, X } from 'lucide-react';

import {
  knowledgeContentTypeSchema,
  knowledgeDocumentStatusSchema,
  knowledgeVisibilitySchema,
  type KnowledgeContentType,
  type KnowledgeDocumentFilters,
  type KnowledgeDocumentStatus,
  type KnowledgeVisibility,
} from './knowledge-contract';
import {
  formatContentType,
  formatDocumentStatus,
  formatKnowledgeVisibility,
} from './knowledge-formatters';

type ToolbarFilters = Pick<KnowledgeDocumentFilters, 'status' | 'contentType' | 'visibility'>;

interface KnowledgeLibraryToolbarProps {
  readonly filters: KnowledgeDocumentFilters;
  readonly isRefreshing: boolean;

  readonly onFiltersChange: (filters: ToolbarFilters) => void;

  readonly onRefresh: () => void;
  readonly onCreateDocument: () => void;
  readonly onUploadDocument: () => void;
}

const documentStatuses = [
  'active',
  'archived',
  'deleted',
] satisfies readonly KnowledgeDocumentStatus[];

const contentTypes = [
  'policy',
  'faq',
  'procedure',
  'guide',
  'reference',
  'other',
] satisfies readonly KnowledgeContentType[];

const visibilityOptions = ['customer', 'internal', 'both'] satisfies readonly KnowledgeVisibility[];

export function KnowledgeLibraryToolbar({
  filters,
  isRefreshing,
  onFiltersChange,
  onRefresh,
  onCreateDocument,
  onUploadDocument,
}: KnowledgeLibraryToolbarProps) {
  const activeFilterCount = [filters.status, filters.contentType, filters.visibility].filter(
    (value) => value !== null,
  ).length;

  function updateStatus(value: string) {
    const parsed = knowledgeDocumentStatusSchema.safeParse(value);

    onFiltersChange({
      status: parsed.success ? parsed.data : null,

      contentType: filters.contentType,
      visibility: filters.visibility,
    });
  }

  function updateContentType(value: string) {
    const parsed = knowledgeContentTypeSchema.safeParse(value);

    onFiltersChange({
      status: filters.status,

      contentType: parsed.success ? parsed.data : null,

      visibility: filters.visibility,
    });
  }

  function updateVisibility(value: string) {
    const parsed = knowledgeVisibilitySchema.safeParse(value);

    onFiltersChange({
      status: filters.status,
      contentType: filters.contentType,

      visibility: parsed.success ? parsed.data : null,
    });
  }

  function clearFilters() {
    onFiltersChange({
      status: null,
      contentType: null,
      visibility: null,
    });
  }

  return (
    <section
      className="knowledge-library-toolbar knowledge-surface"
      aria-label="Document library controls"
    >
      <div className="knowledge-library-toolbar__filters">
        <div className="knowledge-library-toolbar__filter-heading">
          <Filter size={17} aria-hidden="true" />

          <span>Filter documents</span>

          {activeFilterCount > 0 && (
            <span
              className="knowledge-library-toolbar__filter-count"
              aria-label={`${activeFilterCount} active ${
                activeFilterCount === 1 ? 'filter' : 'filters'
              }`}
            >
              {activeFilterCount}
            </span>
          )}
        </div>

        <div className="knowledge-library-toolbar__fields">
          <label>
            <span>Document status</span>

            <select
              value={filters.status ?? ''}
              onChange={(event) => {
                updateStatus(event.currentTarget.value);
              }}
            >
              <option value="">All statuses</option>

              {documentStatuses.map((status) => (
                <option value={status} key={status}>
                  {formatDocumentStatus(status)}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Content type</span>

            <select
              value={filters.contentType ?? ''}
              onChange={(event) => {
                updateContentType(event.currentTarget.value);
              }}
            >
              <option value="">All content types</option>

              {contentTypes.map((contentType) => (
                <option value={contentType} key={contentType}>
                  {formatContentType(contentType)}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Visibility</span>

            <select
              value={filters.visibility ?? ''}
              onChange={(event) => {
                updateVisibility(event.currentTarget.value);
              }}
            >
              <option value="">All audiences</option>

              {visibilityOptions.map((visibility) => (
                <option value={visibility} key={visibility}>
                  {formatKnowledgeVisibility(visibility)}
                </option>
              ))}
            </select>
          </label>

          {activeFilterCount > 0 && (
            <button
              type="button"
              className="knowledge-library-toolbar__clear"
              onClick={clearFilters}
            >
              <X size={16} aria-hidden="true" />
              Clear filters
            </button>
          )}
        </div>
      </div>

      <div className="knowledge-library-toolbar__actions">
        <button
          type="button"
          className="knowledge-library-toolbar__refresh"
          aria-label={isRefreshing ? 'Refreshing document library' : 'Refresh document library'}
          title={isRefreshing ? 'Refreshing document library' : 'Refresh document library'}
          disabled={isRefreshing}
          onClick={onRefresh}
        >
          <RefreshCw
            size={18}
            aria-hidden="true"
            className={isRefreshing ? 'is-spinning' : undefined}
          />

          <span className="knowledge-library-toolbar__refresh-label">
            {isRefreshing ? 'Refreshing…' : 'Refresh'}
          </span>
        </button>

        <button
          type="button"
          className="knowledge-library-toolbar__action knowledge-library-toolbar__action--outline"
          onClick={onCreateDocument}
        >
          <FilePlus2 size={18} aria-hidden="true" />
          Create document
        </button>

        <button
          type="button"
          className="knowledge-library-toolbar__action knowledge-library-toolbar__action--solid"
          onClick={onUploadDocument}
        >
          <Upload size={18} aria-hidden="true" />
          Upload document
        </button>
      </div>
    </section>
  );
}
