// apps/web/src/features/knowledge/knowledge-formatters.ts

import type {
  KnowledgeContentType,
  KnowledgeDocumentStatus,
  KnowledgeIngestionStatus,
  KnowledgeSourceType,
  KnowledgeVersionStatus,
  KnowledgeVisibility,
} from './knowledge-contract';

/* -------------------------------------------------------------------------- */
/*                              Display vocabulary                            */
/* -------------------------------------------------------------------------- */

const documentStatusLabels = {
  active: 'Active',
  archived: 'Archived',
  deleted: 'Deleted',
} satisfies Record<KnowledgeDocumentStatus, string>;

const contentTypeLabels = {
  policy: 'Policy',
  faq: 'FAQ',
  procedure: 'Procedure',
  guide: 'Guide',
  reference: 'Reference',
  other: 'Other',
} satisfies Record<KnowledgeContentType, string>;

const visibilityLabels = {
  customer: 'Customer',
  internal: 'Internal',
  both: 'Customer and internal',
} satisfies Record<KnowledgeVisibility, string>;

const versionStatusLabels = {
  draft: 'Draft',
  processing: 'Processing',
  ready: 'Ready',
  published: 'Published',
  superseded: 'Superseded',
  failed: 'Failed',
  archived: 'Archived',
} satisfies Record<KnowledgeVersionStatus, string>;

const ingestionStatusLabels = {
  pending: 'Pending',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
} satisfies Record<KnowledgeIngestionStatus, string>;

const sourceTypeLabels = {
  markdown: 'Markdown',
  plain_text: 'Plain text',
  pdf: 'PDF',
  docx: 'DOCX',
  html: 'HTML',
  rich_text: 'Rich text',
} satisfies Record<KnowledgeSourceType, string>;

/* -------------------------------------------------------------------------- */
/*                               Status wording                               */
/* -------------------------------------------------------------------------- */

const documentStatusDescriptions = {
  active: 'This document can receive new versions and participate in the publication lifecycle.',

  archived: 'This document is retained for history but cannot receive lifecycle changes.',

  deleted: 'This document is unavailable for normal knowledge operations.',
} satisfies Record<KnowledgeDocumentStatus, string>;

const versionStatusDescriptions = {
  draft: 'This immutable version has been created and is waiting to be processed.',

  processing: 'The source is currently being parsed, normalized, and divided into chunks.',

  ready: 'Processing completed successfully. This version can be embedded or published.',

  published: 'This version is currently available to the support AI.',

  superseded: 'A newer version has replaced this version as the published source.',

  failed:
    'Processing could not be completed. Review the failure information and create a new version.',

  archived: 'This version is retained for historical purposes and is no longer operational.',
} satisfies Record<KnowledgeVersionStatus, string>;

const ingestionStatusDescriptions = {
  pending: 'Ingestion has not started yet.',

  running: 'The ingestion pipeline is currently working on this version.',

  completed: 'The ingestion pipeline completed successfully.',

  failed: 'The ingestion pipeline could not complete this version.',
} satisfies Record<KnowledgeIngestionStatus, string>;

/* -------------------------------------------------------------------------- */
/*                                Visual tones                                */
/* -------------------------------------------------------------------------- */

export type KnowledgeStatusTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'muted';

const documentStatusTones = {
  active: 'success',
  archived: 'muted',
  deleted: 'danger',
} satisfies Record<KnowledgeDocumentStatus, KnowledgeStatusTone>;

const versionStatusTones = {
  draft: 'neutral',
  processing: 'warning',
  ready: 'success',
  published: 'success',
  superseded: 'muted',
  failed: 'danger',
  archived: 'muted',
} satisfies Record<KnowledgeVersionStatus, KnowledgeStatusTone>;

const ingestionStatusTones = {
  pending: 'neutral',
  running: 'warning',
  completed: 'success',
  failed: 'danger',
} satisfies Record<KnowledgeIngestionStatus, KnowledgeStatusTone>;

/* -------------------------------------------------------------------------- */
/*                              Label formatters                              */
/* -------------------------------------------------------------------------- */

export function formatDocumentStatus(status: KnowledgeDocumentStatus): string {
  return documentStatusLabels[status];
}

export function formatContentType(contentType: KnowledgeContentType): string {
  return contentTypeLabels[contentType];
}

export function formatKnowledgeVisibility(visibility: KnowledgeVisibility): string {
  return visibilityLabels[visibility];
}

export function formatVersionStatus(status: KnowledgeVersionStatus): string {
  return versionStatusLabels[status];
}

export function formatIngestionStatus(status: KnowledgeIngestionStatus): string {
  return ingestionStatusLabels[status];
}

export function formatSourceType(sourceType: KnowledgeSourceType): string {
  return sourceTypeLabels[sourceType];
}

/* -------------------------------------------------------------------------- */
/*                            Description helpers                             */
/* -------------------------------------------------------------------------- */

export function describeDocumentStatus(status: KnowledgeDocumentStatus): string {
  return documentStatusDescriptions[status];
}

export function describeVersionStatus(status: KnowledgeVersionStatus): string {
  return versionStatusDescriptions[status];
}

export function describeIngestionStatus(status: KnowledgeIngestionStatus): string {
  return ingestionStatusDescriptions[status];
}

/* -------------------------------------------------------------------------- */
/*                                Tone helpers                                */
/* -------------------------------------------------------------------------- */

export function getDocumentStatusTone(status: KnowledgeDocumentStatus): KnowledgeStatusTone {
  return documentStatusTones[status];
}

export function getVersionStatusTone(status: KnowledgeVersionStatus): KnowledgeStatusTone {
  return versionStatusTones[status];
}

export function getIngestionStatusTone(status: KnowledgeIngestionStatus): KnowledgeStatusTone {
  return ingestionStatusTones[status];
}

/* -------------------------------------------------------------------------- */
/*                              Date formatters                               */
/* -------------------------------------------------------------------------- */

export interface KnowledgeDateFormatOptions {
  readonly locale?: string;
  readonly timeZone?: string;
}

export function formatKnowledgeDate(
  value: string,
  options: KnowledgeDateFormatOptions = {},
): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return 'Invalid date';
  }

  return new Intl.DateTimeFormat(options.locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
    ...(options.timeZone === undefined
      ? {}
      : {
          timeZone: options.timeZone,
        }),
  }).format(date);
}

export function formatOptionalKnowledgeDate(
  value: string | null | undefined,
  options: KnowledgeDateFormatOptions = {},
): string {
  if (value === null || value === undefined) {
    return 'Not available';
  }

  return formatKnowledgeDate(value, options);
}

export function formatRelativeKnowledgeTime(
  value: string,
  now: Date = new Date(),
  locale?: string,
): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return 'Invalid date';
  }

  const differenceSeconds = Math.round((date.getTime() - now.getTime()) / 1_000);

  const absoluteSeconds = Math.abs(differenceSeconds);

  const formatter = new Intl.RelativeTimeFormat(locale, {
    numeric: 'auto',
  });

  if (absoluteSeconds < 60) {
    return formatter.format(differenceSeconds, 'second');
  }

  const differenceMinutes = Math.round(differenceSeconds / 60);

  if (Math.abs(differenceMinutes) < 60) {
    return formatter.format(differenceMinutes, 'minute');
  }

  const differenceHours = Math.round(differenceMinutes / 60);

  if (Math.abs(differenceHours) < 24) {
    return formatter.format(differenceHours, 'hour');
  }

  const differenceDays = Math.round(differenceHours / 24);

  if (Math.abs(differenceDays) < 30) {
    return formatter.format(differenceDays, 'day');
  }

  const differenceMonths = Math.round(differenceDays / 30);

  if (Math.abs(differenceMonths) < 12) {
    return formatter.format(differenceMonths, 'month');
  }

  return formatter.format(Math.round(differenceMonths / 12), 'year');
}

/* -------------------------------------------------------------------------- */
/*                            Numeric formatters                              */
/* -------------------------------------------------------------------------- */

export function formatKnowledgeCount(value: number, locale?: string): string {
  return new Intl.NumberFormat(locale).format(value);
}

export function formatFileSize(bytes: number, locale?: string): string {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return 'Invalid size';
  }

  if (bytes < 1_000) {
    return `${new Intl.NumberFormat(locale).format(bytes)} B`;
  }

  const units = ['KB', 'MB', 'GB', 'TB'] as const;

  let value = bytes / 1_000;
  let unitIndex = 0;

  while (value >= 1_000 && unitIndex < units.length - 1) {
    value /= 1_000;
    unitIndex += 1;
  }

  const formattedValue = new Intl.NumberFormat(locale, {
    maximumFractionDigits: value >= 100 ? 0 : value >= 10 ? 1 : 2,
  }).format(value);

  return `${formattedValue} ${units[unitIndex]}`;
}

export function formatCharacterCount(value: number, locale?: string): string {
  const formatted = formatKnowledgeCount(value, locale);

  return `${formatted} ${value === 1 ? 'character' : 'characters'}`;
}

/* -------------------------------------------------------------------------- */
/*                                Hash helpers                                */
/* -------------------------------------------------------------------------- */

export function shortenContentHash(hash: string): string {
  if (hash.length <= 20) {
    return hash;
  }

  return `${hash.slice(0, 10)}…${hash.slice(-10)}`;
}

export function formatVersionNumber(versionNumber: number): string {
  return `Version ${versionNumber}`;
}

/* -------------------------------------------------------------------------- */
/*                           Failure-code wording                             */
/* -------------------------------------------------------------------------- */

export function formatFailureCode(failureCode: string | null | undefined): string {
  if (failureCode === null || failureCode === undefined || failureCode.trim().length === 0) {
    return 'No failure reported';
  }

  return failureCode
    .trim()
    .replaceAll('_', ' ')
    .replaceAll('-', ' ')
    .replace(/\s+/gu, ' ')
    .replace(/^./u, (character) => character.toUpperCase());
}
