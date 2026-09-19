// apps/web/src/features/operations/ai-activity-page.tsx
import { useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Bot,
  Coins,
  Database,
  Gauge,
  RefreshCw,
  Sparkles,
  Timer,
  Zap,
} from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import type {
  AIAnalytics,
  AIAnalyticsPoint,
  AnalyticsBucket,
  AnalyticsCategoryCount,
  AnalyticsDurationSummary,
} from './ai-activity-contract';
import type { AIAnalyticsWindow } from './ai-activity-api';
import { useAIAnalytics } from './ai-activity-queries';
import { AITraceExplorer } from './ai-trace-explorer';
import { DashboardJellySwitch } from './dashboard-jelly-switch';

import './ai-activity-page.css';

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

function formatDecimal(value: string | null, maximumFractionDigits = 1): string {
  if (value === null) {
    return '—';
  }

  const parsed = Number(value);

  if (!Number.isFinite(parsed)) {
    return '—';
  }

  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits,
  }).format(parsed);
}

function formatCost(value: string): string {
  const parsed = Number(value);

  if (!Number.isFinite(parsed)) {
    return '—';
  }

  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(parsed);
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function formatCategory(value: string): string {
  return value
    .split('_')
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
  readonly icon: typeof Activity;
  readonly label: string;
  readonly value: string;
  readonly supportingText: string;
  readonly tone?: 'neutral' | 'positive' | 'warning' | 'danger';
}) {
  return (
    <article className={`ai-metric-card ai-metric-card--${tone}`}>
      <span className="ai-metric-card__icon">
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

function durationValue(
  duration: AnalyticsDurationSummary,
  percentile: 'average_ms' | 'p50_ms' | 'p95_ms',
): string {
  const value = duration[percentile];

  return value === null ? '—' : `${formatDecimal(value)} ms`;
}

function createPolyline(
  values: readonly number[],
  width: number,
  height: number,
  padding: number,
): string {
  if (values.length === 0) {
    return '';
  }

  const maximum = Math.max(1, ...values);
  const usableWidth = width - padding * 2;
  const usableHeight = height - padding * 2;

  return values
    .map((value, index) => {
      const x =
        values.length === 1 ? width / 2 : padding + (index / (values.length - 1)) * usableWidth;

      const y = height - padding - (value / maximum) * usableHeight;

      return `${x},${y}`;
    })
    .join(' ');
}

function ActivityTimeline({ points }: { readonly points: readonly AIAnalyticsPoint[] }) {
  const width = 720;
  const height = 210;
  const padding = 22;

  const runPoints = createPolyline(
    points.map((point) => point.runs),
    width,
    height,
    padding,
  );

  const failurePoints = createPolyline(
    points.map((point) => point.failed_runs),
    width,
    height,
    padding,
  );

  return (
    <section className="ai-panel ai-timeline-panel">
      <div className="ai-panel__heading">
        <div>
          <p className="operations-kicker">AI run timeline</p>
          <h2>Volume and failure movement</h2>
        </div>

        <div className="ai-chart-legend" aria-label="Chart legend">
          <span className="is-runs">Runs</span>
          <span className="is-failures">Failed</span>
        </div>
      </div>

      {points.length === 0 ? (
        <div className="ai-chart-empty">No AI run activity exists in this window.</div>
      ) : (
        <>
          <svg
            className="ai-timeline-chart"
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label="AI runs and failed runs over time"
            preserveAspectRatio="none"
          >
            <line
              x1={padding}
              y1={height - padding}
              x2={width - padding}
              y2={height - padding}
              className="ai-chart-axis"
            />

            <line
              x1={padding}
              y1={padding}
              x2={padding}
              y2={height - padding}
              className="ai-chart-axis"
            />

            <polyline points={runPoints} className="ai-chart-line ai-chart-line--runs" />

            <polyline points={failurePoints} className="ai-chart-line ai-chart-line--failures" />
          </svg>

          <div className="ai-chart-range">
            <span>{formatTimestamp(points[0]?.bucket_started_at ?? '')}</span>

            <span>{formatTimestamp(points.at(-1)?.bucket_started_at ?? '')}</span>
          </div>
        </>
      )}
    </section>
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
  const visibleItems = [...items].sort((left, right) => right.count - left.count).slice(0, 7);

  const maximum = Math.max(1, ...visibleItems.map((item) => item.count));

  return (
    <section className="ai-panel ai-distribution-panel">
      <div className="ai-panel__heading">
        <div>
          <p className="operations-kicker">{kicker}</p>
          <h2>{title}</h2>
        </div>
      </div>

      {visibleItems.length === 0 ? (
        <p className="ai-distribution-empty">{emptyMessage}</p>
      ) : (
        <ol>
          {visibleItems.map((item) => {
            const width = (item.count / maximum) * 100;

            return (
              <li key={item.category}>
                <div>
                  <span>{formatCategory(item.category)}</span>
                  <strong>{formatInteger(item.count)}</strong>
                </div>

                <span className="ai-distribution-track">
                  <span
                    style={{
                      width: `${Math.max(width, 2)}%`,
                    }}
                  />
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function PipelineCard({
  title,
  total,
  successful,
  failed,
  timedOut,
  duration,
}: {
  readonly title: string;
  readonly total: number;
  readonly successful: number;
  readonly failed: number;
  readonly timedOut: number;
  readonly duration: AnalyticsDurationSummary;
}) {
  return (
    <article className="ai-pipeline-card">
      <div>
        <strong>{title}</strong>
        <span>{formatInteger(total)} total</span>
      </div>

      <dl>
        <div>
          <dt>Successful</dt>
          <dd>{formatInteger(successful)}</dd>
        </div>

        <div>
          <dt>Failed</dt>
          <dd>{formatInteger(failed)}</dd>
        </div>

        <div>
          <dt>Timed out</dt>
          <dd>{formatInteger(timedOut)}</dd>
        </div>

        <div>
          <dt>P95 latency</dt>
          <dd>{durationValue(duration, 'p95_ms')}</dd>
        </div>
      </dl>
    </article>
  );
}

function FailureSignals({ analytics }: { readonly analytics: AIAnalytics }) {
  const signals = [
    ...analytics.llm_error_code_distribution.map((item) => ({
      ...item,
      source: 'LLM',
    })),
    ...analytics.retrieval_error_code_distribution.map((item) => ({
      ...item,
      source: 'Retrieval',
    })),
    ...analytics.reranker_error_code_distribution.map((item) => ({
      ...item,
      source: 'Reranker',
    })),
    ...analytics.embedding_error_code_distribution.map((item) => ({
      ...item,
      source: 'Embedding',
    })),
    ...analytics.guardrail_error_code_distribution.map((item) => ({
      ...item,
      source: 'Guardrail',
    })),
  ]
    .sort((left, right) => right.count - left.count)
    .slice(0, 8);

  return (
    <section className="ai-panel ai-failure-panel">
      <div className="ai-panel__heading">
        <div>
          <p className="operations-kicker">Diagnostic signals</p>
          <h2>Failures and guardrails</h2>
        </div>

        <AlertTriangle size={21} aria-hidden="true" />
      </div>

      {signals.length === 0 ? (
        <div className="ai-healthy-state">
          <span>
            <Sparkles size={20} aria-hidden="true" />
          </span>

          <div>
            <strong>No recorded failure codes</strong>
            <p>
              No provider, retrieval, reranker, embedding, or guardrail error code was recorded
              during this window.
            </p>
          </div>
        </div>
      ) : (
        <div className="ai-failure-list">
          {signals.map((signal) => (
            <div key={`${signal.source}-${signal.category}`}>
              <span>
                <small>{signal.source}</small>
                <strong>{formatCategory(signal.category)}</strong>
              </span>

              <strong>{formatInteger(signal.count)}</strong>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function AIActivityContent({ analytics }: { readonly analytics: AIAnalytics }) {
  const noActivity =
    analytics.total_runs === 0 &&
    analytics.total_llm_calls === 0 &&
    analytics.retrieval_runs === 0 &&
    analytics.embedding_calls === 0;

  return (
    <>
      <section className="ai-metric-grid" aria-label="AI activity summary">
        <MetricCard
          icon={Activity}
          label="AI runs"
          value={formatInteger(analytics.total_runs)}
          supportingText={`${formatInteger(analytics.running_runs)} currently running`}
        />

        <MetricCard
          icon={Gauge}
          label="Success rate"
          value={formatPercentage(analytics.success_rate)}
          supportingText={`${formatInteger(analytics.failed_runs)} failed · ${formatInteger(
            analytics.cancelled_runs,
          )} cancelled`}
          tone={analytics.failed_runs > 0 ? 'warning' : 'positive'}
        />

        <MetricCard
          icon={Timer}
          label="Run P95"
          value={durationValue(analytics.run_duration, 'p95_ms')}
          supportingText={`${formatInteger(analytics.run_duration.sample_count)} measured runs`}
        />

        <MetricCard
          icon={Coins}
          label="Estimated cost"
          value={formatCost(analytics.estimated_cost_usd)}
          supportingText="Backend-calculated estimate"
        />

        <MetricCard
          icon={Bot}
          label="LLM tokens"
          value={formatInteger(analytics.input_tokens + analytics.output_tokens)}
          supportingText={`${formatInteger(analytics.cached_input_tokens)} cached input tokens`}
        />

        <MetricCard
          icon={Database}
          label="Zero-result rate"
          value={formatPercentage(analytics.zero_result_rate)}
          supportingText={`${formatInteger(
            analytics.zero_result_retrievals,
          )} zero-result retrievals`}
          tone={analytics.zero_result_retrievals > 0 ? 'warning' : 'neutral'}
        />
      </section>

      {noActivity ? (
        <section className="ai-empty-state">
          <span>
            <Sparkles size={28} aria-hidden="true" />
          </span>

          <h2>No AI activity in this window</h2>

          <p>Select a broader reporting window or refresh after processing customer messages.</p>
        </section>
      ) : (
        <>
          <ActivityTimeline points={analytics.timeline} />

          <section className="ai-pipeline-panel">
            <div className="ai-panel__heading">
              <div>
                <p className="operations-kicker">Pipeline health</p>
                <h2>Service execution</h2>
              </div>

              <Zap size={21} aria-hidden="true" />
            </div>

            <div className="ai-pipeline-grid">
              <PipelineCard
                title="LLM calls"
                total={analytics.total_llm_calls}
                successful={analytics.successful_llm_calls}
                failed={analytics.failed_llm_calls}
                timedOut={analytics.timed_out_llm_calls}
                duration={analytics.llm_call_duration}
              />

              <PipelineCard
                title="Retrieval"
                total={analytics.retrieval_runs}
                successful={analytics.successful_retrieval_runs}
                failed={analytics.failed_retrieval_runs}
                timedOut={analytics.timed_out_retrieval_runs}
                duration={analytics.retrieval_duration}
              />

              <PipelineCard
                title="Reranker"
                total={analytics.reranker_calls}
                successful={analytics.successful_reranker_calls}
                failed={analytics.failed_reranker_calls}
                timedOut={analytics.timed_out_reranker_calls}
                duration={analytics.reranker_duration}
              />

              <PipelineCard
                title="Embeddings"
                total={analytics.embedding_calls}
                successful={analytics.successful_embedding_calls}
                failed={analytics.failed_embedding_calls}
                timedOut={analytics.timed_out_embedding_calls}
                duration={analytics.embedding_duration}
              />
            </div>
          </section>

          <div className="ai-distribution-grid">
            <DistributionPanel
              kicker="Classification"
              title="Intent distribution"
              items={analytics.intent_distribution}
              emptyMessage="No classified intents were recorded."
            />

            <DistributionPanel
              kicker="Orchestration"
              title="Decision distribution"
              items={analytics.decision_distribution}
              emptyMessage="No orchestration decisions were recorded."
            />

            <DistributionPanel
              kicker="Providers"
              title="LLM provider usage"
              items={analytics.llm_provider_distribution}
              emptyMessage="No LLM provider usage was recorded."
            />

            <DistributionPanel
              kicker="Models"
              title="LLM model usage"
              items={analytics.llm_model_distribution}
              emptyMessage="No model usage was recorded."
            />
          </div>

          <FailureSignals analytics={analytics} />
        </>
      )}
    </>
  );
}

export function AIActivityPage() {
  const [preset, setPreset] = useState<WindowPreset>('24h');

  const [windowAnchor, setWindowAnchor] = useState(() => Date.now());

  const window = useMemo<AIAnalyticsWindow>(() => {
    const configuration = presetConfiguration[preset];

    return {
      startedAt: new Date(windowAnchor - configuration.durationMs).toISOString(),

      endedAt: new Date(windowAnchor).toISOString(),

      bucket: configuration.bucket,
    };
  }, [preset, windowAnchor]);

  const analytics = useAIAnalytics(window);

  return (
    <div className="ai-activity">
      <section className="ai-activity-toolbar">
        <DashboardJellySwitch
          label="AI activity reporting window"
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

        <div className="ai-activity-toolbar__meta">
          {analytics.data ? (
            <span>Generated {formatTimestamp(analytics.data.metadata.generated_at)}</span>
          ) : null}

          <button
            type="button"
            className="operations-icon-button ai-activity-refresh"
            aria-label="Refresh AI activity"
            title="Refresh AI activity"
            disabled={analytics.isFetching}
            onClick={() => {
              setWindowAnchor(Date.now());
            }}
          >
            <RefreshCw
              size={19}
              aria-hidden="true"
              className={analytics.isFetching ? 'is-spinning' : undefined}
            />
          </button>
        </div>
      </section>

      {analytics.isPending && analytics.data === undefined ? (
        <div className="ai-activity-loading" aria-label="Loading AI activity" aria-busy="true">
          <div className="ai-metric-grid">
            {Array.from({ length: 6 }, (_, index) => (
              <div className="operations-skeleton ai-metric-skeleton" key={index} />
            ))}
          </div>

          <div className="operations-skeleton ai-panel-skeleton" />
          <div className="operations-skeleton ai-panel-skeleton" />
        </div>
      ) : null}

      {analytics.isError && analytics.data === undefined ? (
        <section className="ai-error-state" role="alert">
          <span>
            <CircleAlertIcon />
          </span>

          <h2>AI activity unavailable</h2>

          <p>{safeErrorMessage(analytics.error, 'AI analytics could not be loaded.')}</p>

          <button
            type="button"
            className="operations-button operations-button--primary"
            onClick={() => {
              void analytics.refetch();
            }}
          >
            Try again
          </button>
        </section>
      ) : null}

      {analytics.data ? (
        <>
          <AIActivityContent analytics={analytics.data} />

          <AITraceExplorer key={`${window.startedAt}-${window.endedAt}`} window={window} />
        </>
      ) : null}
    </div>
  );
}

function CircleAlertIcon() {
  return <AlertTriangle size={27} aria-hidden="true" />;
}
