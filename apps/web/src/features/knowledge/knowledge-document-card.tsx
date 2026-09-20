// apps/web/src/features/knowledge/knowledge-document-card.tsx

import { Link } from 'react-router';
import {
  ArrowUpRight,
  BookOpen,
  CircleHelp,
  ClipboardList,
  Eye,
  FileText,
  LibraryBig,
  ScrollText,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import type { KnowledgeContentType, KnowledgeDocument } from './knowledge-contract';
import {
  formatContentType,
  formatDocumentStatus,
  formatKnowledgeDate,
  formatKnowledgeVisibility,
  formatRelativeKnowledgeTime,
  getDocumentStatusTone,
} from './knowledge-formatters';

interface KnowledgeDocumentCardProps {
  readonly document: KnowledgeDocument;
}

const contentTypeIcons = {
  policy: ScrollText,
  faq: CircleHelp,
  procedure: ClipboardList,
  guide: BookOpen,
  reference: LibraryBig,
  other: FileText,
} satisfies Record<KnowledgeContentType, LucideIcon>;

function getDocumentCardClasses(document: KnowledgeDocument): string {
  return [
    'knowledge-document-card',
    'knowledge-surface',

    document.status === 'archived' ? 'is-archived' : '',

    document.status === 'deleted' ? 'is-deleted' : '',
  ]
    .filter(Boolean)
    .join(' ');
}

export function KnowledgeDocumentCard({ document }: KnowledgeDocumentCardProps) {
  const ContentTypeIcon = contentTypeIcons[document.content_type];

  const statusTone = getDocumentStatusTone(document.status);

  const absoluteUpdatedAt = formatKnowledgeDate(document.updated_at);

  const relativeUpdatedAt = formatRelativeKnowledgeTime(document.updated_at);

  const description =
    document.description?.trim() || 'No description has been provided for this document.';

  return (
    <article className={getDocumentCardClasses(document)} data-document-status={document.status}>
      <div className="knowledge-document-card__top">
        <span className="knowledge-document-card__icon" aria-hidden="true">
          <ContentTypeIcon size={20} />
        </span>

        <span className={['knowledge-status', `knowledge-status--${statusTone}`].join(' ')}>
          {formatDocumentStatus(document.status)}
        </span>
      </div>

      <div className="knowledge-document-card__body">
        <span className="knowledge-document-card__type">
          {formatContentType(document.content_type)}
        </span>

        <h3>
          <Link
            className="knowledge-document-card__link"
            to={`/knowledge/documents/${document.document_id}`}
          >
            <span>{document.title}</span>

            <span className="knowledge-document-card__link-indicator" aria-hidden="true">
              <ArrowUpRight size={16} />
            </span>
          </Link>
        </h3>

        <p className="knowledge-document-card__description">{description}</p>

        <div className="knowledge-document-card__metadata">
          <span>
            <Eye size={14} aria-hidden="true" />

            <span>{formatKnowledgeVisibility(document.visibility)}</span>
          </span>

          <span>
            <span>Updated</span>

            <time dateTime={document.updated_at} title={absoluteUpdatedAt}>
              {relativeUpdatedAt}
            </time>
          </span>
        </div>
      </div>
    </article>
  );
}
