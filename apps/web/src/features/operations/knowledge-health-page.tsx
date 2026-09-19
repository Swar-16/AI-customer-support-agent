// apps/web/src/features/operations/knowledge-health-page.tsx
import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import {
  BookOpenCheck,
  Boxes,
  CircleAlert,
  Clock3,
  Database,
  FileCheck2,
  FileWarning,
  Layers3,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  UploadCloud,
} from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import type { AnalyticsBucket, AnalyticsCategoryCount } from './ai-activity-contract';
import type { KnowledgeHealthWindow } from './knowledge-health-api';
import type { KnowledgeHealth, KnowledgeHealthPoint } from './knowledge-health-contract';
import { useKnowledgeHealth } from './knowledge-health-queries';
import { DashboardJellySwitch } from './dashboard-jelly-switch';

import './knowledge-health-page.css';

type WindowPreset = '24h' | '7d' | '30d';

const presetConfiguration: Record<
  WindowPreset,
  {
    readonly label: string;
    readonly durationMs: number;
    readonly bucket: AnalyticsBucket;
  }
> = {
  '24h': {
    label: '24 hours',
    durationMs: 24 * 60 * 60 * 1_000,
    bucket: 'hour',
  },
  '7d': {
    label: '7 days',
    durationMs: 7 * 24 * 60 * 60 * 1_000,
    bucket: 'day',
  },
  '30d': {
    label: '30 days',
    durationMs: 30 * 24 * 60 * 60 * 1_000,
    bucket: 'day',
  },
};

function safeErrorMessage(error: unknown, fallback: string): string {
  return error instanceof SafeApiError ? error.message : fallback;
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat().format(value);
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function formatPercentage(value: string | null): string {
  if (value === null) {
    return '—';
  }

  const parsed = Number(value);

  if (!Number.isFinite(parsed)) {
    return '—';
  }

  return new Intl.NumberFormat(undefined, {
    style: 'percent',
    maximumFractionDigits: 1,
  }).format(parsed);
}

function formatDuration(value: string | null): string {
  if (value === null) {
    return '—';
  }

  const parsed = Number(value);

  if (!Number.isFinite(parsed)) {
    return '—';
  }

  if (parsed < 1_000) {
    return `${new Intl.NumberFormat(undefined, {
      maximumFractionDigits: 1,
    }).format(parsed)} ms`;
  }

  return `${(parsed / 1_000).toFixed(2)} s`;
}

function formatCategory(value: string): string {
  return value
    .split(/[._-]/u)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ');
}

function MetricCard({
  icon: Icon,
  label,
  value,
  supportingText,
  tone = 'neutral',
}: {
  readonly icon: typeof Database;
  readonly label: string;
  readonly value: string;
  readonly supportingText: string;
  readonly tone?: 'neutral' | 'positive' | 'warning' | 'danger';
}) {
  return (
    <article className={`knowledge-metric knowledge-metric--${tone}`}>
      <span className="knowledge-metric__icon">
        <Icon size={20} aria-hidden="true" />
      </span>

      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{supportingText}</small>
      </div>
    </article>
  );
}

function DistributionPanel({
  title,
  kicker,
  items,
  emptyMessage,
}: {
  readonly title: string;
  readonly kicker: string;
  readonly items: readonly AnalyticsCategoryCount[];
  readonly emptyMessage: string;
}) {
  const visibleItems = [...items].sort((left, right) => right.count - left.count).slice(0, 8);

  const maximum = Math.max(1, ...visibleItems.map((item) => item.count));

  return (
    <section className="knowledge-panel knowledge-distribution">
      <div className="knowledge-panel__heading">
        <div>
          <p className="operations-kicker">{kicker}</p>
          <h2>{title}</h2>
        </div>
      </div>

      {visibleItems.length === 0 ? (
        <p className="knowledge-distribution__empty">{emptyMessage}</p>
      ) : (
        <ol>
          {visibleItems.map((item) => (
            <li key={item.category}>
              <div>
                <span>{formatCategory(item.category)}</span>
                <strong>{formatInteger(item.count)}</strong>
              </div>

              <span className="knowledge-distribution__track">
                <span
                  style={{
                    width: `${Math.max(2, (item.count / maximum) * 100)}%`,
                  }}
                />
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

interface PlotPoint {
  readonly x: number;
  readonly y: number;
}

function createPlotPoints(
  values: readonly number[],
  width: number,
  height: number,
  padding: number,
): PlotPoint[] {
  if (values.length === 0) {
    return [];
  }

  const maximum = Math.max(1, ...values);
  const usableWidth = width - padding * 2;
  const usableHeight = height - padding * 2;

  return values.map((value, index) => ({
    x: values.length === 1 ? width / 2 : padding + (index / (values.length - 1)) * usableWidth,

    y: height - padding - (value / maximum) * usableHeight,
  }));
}

function polyline(points: readonly PlotPoint[]): string {
  return points.map((point) => `${point.x},${point.y}`).join(' ');
}

function KnowledgeTimeline({ points }: { readonly points: readonly KnowledgeHealthPoint[] }) {
  const width = 720;
  const height = 210;
  const padding = 22;

  const created = createPlotPoints(
    points.map((point) => point.versions_created),
    width,
    height,
    padding,
  );

  const completed = createPlotPoints(
    points.map((point) => point.processing_completed),
    width,
    height,
    padding,
  );

  const failed = createPlotPoints(
    points.map((point) => point.processing_failed),
    width,
    height,
    padding,
  );

  return (
    <section className="knowledge-panel knowledge-timeline-panel">
      <div className="knowledge-panel__heading">
        <div>
          <p className="operations-kicker">Processing timeline</p>
          <h2>Version and ingestion movement</h2>
        </div>

        <div className="knowledge-chart-legend" aria-label="Chart legend">
          <span className="is-created">Created</span>
          <span className="is-completed">Completed</span>
          <span className="is-failed">Failed</span>
        </div>
      </div>

      {points.length === 0 ? (
        <div className="knowledge-chart-empty">
          No knowledge processing events exist in this window.
        </div>
      ) : (
        <>
          <svg
            className="knowledge-timeline-chart"
            viewBox={`0 0 ${width} ${height}`}
            preserveAspectRatio="none"
            role="img"
            aria-label="Created versions, completed processing, and failed processing over time"
          >
            <line
              x1={padding}
              y1={height - padding}
              x2={width - padding}
              y2={height - padding}
              className="knowledge-chart-axis"
            />

            <line
              x1={padding}
              y1={padding}
              x2={padding}
              y2={height - padding}
              className="knowledge-chart-axis"
            />

            <polyline
              points={polyline(created)}
              className="knowledge-chart-line knowledge-chart-line--created"
            />

            <polyline
              points={polyline(completed)}
              className="knowledge-chart-line knowledge-chart-line--completed"
            />

            <polyline
              points={polyline(failed)}
              className="knowledge-chart-line knowledge-chart-line--failed"
            />

            {created.map((point, index) => (
              <circle
                key={`created-${index}`}
                cx={point.x}
                cy={point.y}
                r="3"
                className="knowledge-chart-point knowledge-chart-point--created"
              />
            ))}

            {completed.map((point, index) => (
              <circle
                key={`completed-${index}`}
                cx={point.x}
                cy={point.y}
                r="3"
                className="knowledge-chart-point knowledge-chart-point--completed"
              />
            ))}

            {failed.map((point, index) => (
              <circle
                key={`failed-${index}`}
                cx={point.x}
                cy={point.y}
                r="3"
                className="knowledge-chart-point knowledge-chart-point--failed"
              />
            ))}
          </svg>

          <div className="knowledge-chart-range">
            <span>{formatTimestamp(points[0]?.bucket_started_at ?? '')}</span>

            <span>{formatTimestamp(points.at(-1)?.bucket_started_at ?? '')}</span>
          </div>
        </>
      )}
    </section>
  );
}

function KnowledgeHealthStatus({ health }: { readonly health: KnowledgeHealth }) {
  const processingFailures = health.timeline.reduce(
    (total, point) => total + point.processing_failed,
    0,
  );

  const hasProblems =
    health.processing_backlog > 0 ||
    health.versions_without_chunks > 0 ||
    health.versions_missing_embeddings > 0 ||
    processingFailures > 0 ||
    health.failure_code_distribution.length > 0;

  return (
    <section className={`knowledge-health-status${hasProblems ? ' has-warning' : ' is-healthy'}`}>
      <span>
        {hasProblems ? (
          <FileWarning size={23} aria-hidden="true" />
        ) : (
          <ShieldCheck size={23} aria-hidden="true" />
        )}
      </span>

      <div>
        <strong>
          {hasProblems ? 'Knowledge health needs attention' : 'Knowledge inventory is healthy'}
        </strong>

        <p>
          {hasProblems
            ? 'Review processing backlog, missing chunks, embedding coverage, and recent failure codes before publishing additional content.'
            : 'No processing backlog, missing knowledge artifacts, or recent failure codes were detected.'}
        </p>
      </div>

      <Link className="operations-button operations-button--primary" to="/knowledge">
        <BookOpenCheck size={17} aria-hidden="true" />
        Open Knowledge workspace
      </Link>
    </section>
  );
}

function FailurePanel({ health }: { readonly health: KnowledgeHealth }) {
  const failures = [...health.failure_code_distribution].sort(
    (left, right) => right.count - left.count,
  );

  return (
    <section className="knowledge-panel knowledge-failure-panel">
      <div className="knowledge-panel__heading">
        <div>
          <p className="operations-kicker">Failure diagnostics</p>
          <h2>Processing failure codes</h2>
        </div>

        <CircleAlert size={21} aria-hidden="true" />
      </div>

      {failures.length === 0 ? (
        <div className="knowledge-no-failures">
          <span>
            <Sparkles size={20} aria-hidden="true" />
          </span>

          <div>
            <strong>No failure codes recorded</strong>
            <p>The selected reporting window contains no knowledge-processing failure codes.</p>
          </div>
        </div>
      ) : (
        <div className="knowledge-failure-list">
          {failures.map((failure) => (
            <div key={failure.category}>
              <span>{formatCategory(failure.category)}</span>
              <strong>{formatInteger(failure.count)}</strong>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function KnowledgeHealthContent({ health }: { readonly health: KnowledgeHealth }) {
  return (
    <>
      <KnowledgeHealthStatus health={health} />

      <section className="knowledge-metric-grid" aria-label="Knowledge health summary">
        <MetricCard
          icon={Database}
          label="Documents"
          value={formatInteger(health.total_documents)}
          supportingText={`${formatInteger(health.total_versions)} versions`}
        />

        <MetricCard
          icon={Layers3}
          label="Chunks"
          value={formatInteger(health.total_chunks)}
          supportingText={`${formatInteger(
            health.versions_without_chunks,
          )} versions without chunks`}
          tone={health.versions_without_chunks > 0 ? 'warning' : 'positive'}
        />

        <MetricCard
          icon={Boxes}
          label="Embeddings"
          value={formatInteger(health.total_embeddings)}
          supportingText={`${formatInteger(
            health.versions_missing_embeddings,
          )} versions missing embeddings`}
          tone={health.versions_missing_embeddings > 0 ? 'warning' : 'positive'}
        />

        <MetricCard
          icon={FileCheck2}
          label="Embedding coverage"
          value={formatPercentage(health.embedding_coverage_rate)}
          supportingText="Current version snapshot"
          tone={health.versions_missing_embeddings === 0 ? 'positive' : 'warning'}
        />

        <MetricCard
          icon={UploadCloud}
          label="Processing backlog"
          value={formatInteger(health.processing_backlog)}
          supportingText="Current queued or processing work"
          tone={health.processing_backlog > 0 ? 'warning' : 'positive'}
        />

        <MetricCard
          icon={Clock3}
          label="Processing P95"
          value={formatDuration(health.processing_duration.p95_ms)}
          supportingText={`${formatInteger(
            health.processing_duration.sample_count,
          )} completed samples`}
        />
      </section>

      <KnowledgeTimeline points={health.timeline} />

      <div className="knowledge-distribution-grid">
        <DistributionPanel
          kicker="Documents"
          title="Document lifecycle"
          items={health.document_status_distribution}
          emptyMessage="No document status data is available."
        />

        <DistributionPanel
          kicker="Versions"
          title="Version readiness"
          items={health.version_status_distribution}
          emptyMessage="No version status data is available."
        />

        <DistributionPanel
          kicker="Ingestion"
          title="Ingestion status"
          items={health.ingestion_status_distribution}
          emptyMessage="No ingestion status data is available."
        />

        <DistributionPanel
          kicker="Inventory"
          title="Content types"
          items={health.document_content_type_distribution}
          emptyMessage="No content-type data is available."
        />

        <DistributionPanel
          kicker="Access"
          title="Document visibility"
          items={health.document_visibility_distribution}
          emptyMessage="No visibility data is available."
        />

        <FailurePanel health={health} />
      </div>
    </>
  );
}

export function KnowledgeHealthPage() {
  const [preset, setPreset] = useState<WindowPreset>('24h');

  const [windowAnchor, setWindowAnchor] = useState(() => Date.now());

  const window = useMemo<KnowledgeHealthWindow>(() => {
    const configuration = presetConfiguration[preset];

    return {
      startedAt: new Date(windowAnchor - configuration.durationMs).toISOString(),

      endedAt: new Date(windowAnchor).toISOString(),

      bucket: configuration.bucket,
    };
  }, [preset, windowAnchor]);

  const health = useKnowledgeHealth(window);

  return (
    <div className="knowledge-health">
      <section className="knowledge-health-toolbar">
        <DashboardJellySwitch
          label="Knowledge health reporting window"
          value={preset}
          tone="accent"
          options={(
            Object.entries(presetConfiguration) as Array<
              [WindowPreset, (typeof presetConfiguration)[WindowPreset]]
            >
          ).map(([value, configuration]) => ({
            value,
            label: configuration.label,
          }))}
          onChange={(value) => {
            setPreset(value);
            setWindowAnchor(Date.now());
          }}
        />

        <div className="knowledge-health-toolbar__meta">
          {health.data ? (
            <span>Snapshot {formatTimestamp(health.data.snapshot_measured_at)}</span>
          ) : null}

          <button
            type="button"
            className="operations-icon-button knowledge-health-refresh"
            aria-label="Refresh knowledge health"
            title="Refresh knowledge health"
            disabled={health.isFetching}
            onClick={() => {
              setWindowAnchor(Date.now());
            }}
          >
            <RefreshCw
              size={19}
              aria-hidden="true"
              className={health.isFetching ? 'is-spinning' : undefined}
            />
          </button>
        </div>
      </section>

      {health.isPending && health.data === undefined ? (
        <div
          className="knowledge-health-loading"
          aria-label="Loading knowledge health"
          aria-busy="true"
        >
          <div className="knowledge-metric-grid">
            {Array.from({ length: 6 }, (_, index) => (
              <div className="operations-skeleton knowledge-metric-skeleton" key={index} />
            ))}
          </div>

          <div className="operations-skeleton knowledge-panel-skeleton" />
          <div className="operations-skeleton knowledge-panel-skeleton" />
        </div>
      ) : null}

      {health.isError && health.data === undefined ? (
        <section className="knowledge-health-error" role="alert">
          <span>
            <CircleAlert size={28} aria-hidden="true" />
          </span>

          <h2>Knowledge health unavailable</h2>

          <p>{safeErrorMessage(health.error, 'Knowledge health could not be loaded.')}</p>

          <button
            type="button"
            className="operations-button operations-button--primary"
            onClick={() => {
              void health.refetch();
            }}
          >
            Try again
          </button>
        </section>
      ) : null}

      {health.data ? <KnowledgeHealthContent health={health.data} /> : null}
    </div>
  );
}
