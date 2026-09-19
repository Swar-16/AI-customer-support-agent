// apps/web/src/features/operations/operations-overview.tsx
import { useState } from 'react';
import { Link } from 'react-router';
import {
  Activity,
  Bot,
  CircleAlert,
  Clock3,
  RefreshCw,
  ShieldCheck,
  Star,
  TicketCheck,
} from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import { overviewWindows, type OverviewWindow } from './operations-api';
import {
  findOverviewMetric,
  type DashboardOverview,
  type DashboardOverviewMetric,
} from './operations-contract';
import { useDashboardOverview } from './operations-queries';

const windowLabels: Record<OverviewWindow, string> = {
  '24h': '24 hours',
  '7d': '7 days',
  '30d': '30 days',
};

function metric(
  overview: DashboardOverview,
  section: string,
  key: string,
): DashboardOverviewMetric | null {
  return findOverviewMetric(overview, section, key);
}

function metricNumber(overview: DashboardOverview, section: string, key: string): number {
  return metric(overview, section, key)?.value ?? 0;
}

function formatMetric(value: DashboardOverviewMetric | null): string {
  if (value === null || value.metadata.has_data === false) return '—';

  switch (value.unit) {
    case 'percent':
      return `${value.value.toLocaleString(undefined, {
        maximumFractionDigits: 1,
      })}%`;

    case 'milliseconds':
      return `${value.value.toLocaleString(undefined, {
        maximumFractionDigits: 0,
      })} ms`;

    case 'minutes':
      return `${value.value.toLocaleString(undefined, {
        maximumFractionDigits: 1,
      })} min`;

    case 'usd':
      return value.value.toLocaleString(undefined, {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 4,
      });

    default:
      return value.value.toLocaleString(undefined, {
        maximumFractionDigits: 1,
      });
  }
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function OverviewSkeleton() {
  return (
    <div className="operations-overview" aria-busy="true">
      <div className="operations-skeleton operations-skeleton--toolbar" />

      <div className="operations-stat-grid">
        {Array.from({ length: 4 }, (_, index) => (
          <div className="operations-skeleton operations-skeleton--stat" key={index} />
        ))}
      </div>

      <div className="operations-overview-grid">
        <div className="operations-skeleton operations-skeleton--panel" />
        <div className="operations-skeleton operations-skeleton--panel" />
      </div>
    </div>
  );
}

interface AttentionItem {
  readonly label: string;
  readonly detail: string;
  readonly value: number;
  readonly destination: string;
}

export function OperationsOverview() {
  const [window, setWindow] = useState<OverviewWindow>('24h');
  const overview = useDashboardOverview(window);

  if (overview.isPending && overview.data === undefined) {
    return <OverviewSkeleton />;
  }

  if (overview.data === undefined) {
    const message =
      overview.error instanceof SafeApiError
        ? overview.error.message
        : 'The operational overview could not be loaded.';

    return (
      <section className="operations-state-card" role="alert">
        <CircleAlert aria-hidden="true" />
        <div>
          <h2>Overview unavailable</h2>
          <p>{message}</p>
          <button
            type="button"
            className="operations-button operations-button--primary"
            onClick={() => {
              void overview.refetch();
            }}
          >
            Try again
          </button>
        </div>
      </section>
    );
  }

  const data = overview.data;

  const spotlightCards = [
    {
      label: 'Open escalations',
      value: metric(data, 'escalations', 'open'),
      icon: ShieldCheck,
      destination: '/operations/escalations',
    },
    {
      label: 'Active tickets',
      value: metric(data, 'tickets', 'active'),
      icon: TicketCheck,
      destination: '/operations/tickets',
    },
    {
      label: 'Feedback awaiting review',
      value: metric(data, 'feedback', 'pending'),
      icon: Star,
      destination: '/operations/feedback',
    },
    {
      label: 'AI runs in progress',
      value: metric(data, 'ai_runs', 'running_runs'),
      icon: Bot,
      destination: '/operations/ai-activity',
    },
  ] as const;

  const attentionItems: AttentionItem[] = [
    {
      label: 'Urgent escalations',
      detail: 'Require immediate support review',
      value: metricNumber(data, 'escalations', 'urgent_priority_active'),
      destination: '/operations/escalations',
    },
    {
      label: 'High-priority escalations',
      detail: 'Active high-priority customer cases',
      value: metricNumber(data, 'escalations', 'high_priority_active'),
      destination: '/operations/escalations',
    },
    {
      label: 'Unassigned tickets',
      detail: 'Active tickets without an owner',
      value: metricNumber(data, 'tickets', 'unassigned_active'),
      destination: '/operations/tickets',
    },
    {
      label: 'Failed knowledge versions',
      detail: 'Knowledge processing requires attention',
      value: metricNumber(data, 'knowledge', 'failed'),
      destination: '/operations/knowledge-health',
    },
  ].filter((item) => item.value > 0);

  const systemSignals = [
    {
      label: 'API error rate',
      value: metric(data, 'api', 'error_rate'),
      icon: Activity,
    },
    {
      label: 'AI success rate',
      value: metric(data, 'ai_runs', 'success_rate'),
      icon: Bot,
    },
    {
      label: 'Retrieval zero-result rate',
      value: metric(data, 'retrieval', 'zero_result_rate'),
      icon: CircleAlert,
    },
    {
      label: 'Average feedback rating',
      value: metric(data, 'feedback', 'average_rating'),
      icon: Star,
      suffix: ' / 5',
    },
  ] as const;

  return (
    <div className="operations-overview">
      <div className="operations-toolbar">
        <div>
          <p className="operations-toolbar__eyebrow">
            <Clock3 size={15} aria-hidden="true" />
            Generated {formatTimestamp(data.generated_at)}
          </p>
          <p className="operations-toolbar__range">
            {formatTimestamp(data.time_range.started_at)} to{' '}
            {formatTimestamp(data.time_range.ended_at)}
          </p>
        </div>

        <div className="operations-toolbar__actions">
          <div className="operations-window-picker" aria-label="Overview period">
            {overviewWindows.map((candidate) => (
              <button
                type="button"
                aria-pressed={candidate === window}
                key={candidate}
                onClick={() => {
                  setWindow(candidate);
                }}
              >
                {windowLabels[candidate]}
              </button>
            ))}
          </div>

          <button
            type="button"
            className="operations-icon-button"
            aria-label="Refresh overview"
            title="Refresh overview"
            disabled={overview.isFetching}
            onClick={() => {
              void overview.refetch();
            }}
          >
            <RefreshCw
              size={18}
              aria-hidden="true"
              className={overview.isFetching ? 'is-spinning' : undefined}
            />
          </button>
        </div>
      </div>

      {overview.isError ? (
        <p className="operations-inline-warning" role="status">
          The latest refresh failed. Previously loaded metrics are still shown.
        </p>
      ) : null}

      <section aria-labelledby="overview-priorities-title">
        <div className="operations-section-heading">
          <div>
            <p className="operations-kicker">Right now</p>
            <h2 id="overview-priorities-title">Operational priorities</h2>
          </div>
        </div>

        <div className="operations-stat-grid">
          {spotlightCards.map((card) => {
            const Icon = card.icon;

            return (
              <Link className="operations-stat-card" to={card.destination} key={card.label}>
                <span className="operations-stat-card__icon">
                  <Icon size={20} aria-hidden="true" />
                </span>

                <span className="operations-stat-card__value">{formatMetric(card.value)}</span>

                <span className="operations-stat-card__label">{card.label}</span>
              </Link>
            );
          })}
        </div>
      </section>

      <div className="operations-overview-grid">
        <section className="operations-panel" aria-labelledby="attention-title">
          <div className="operations-section-heading">
            <div>
              <p className="operations-kicker">Queue health</p>
              <h2 id="attention-title">Needs attention</h2>
            </div>
          </div>

          {attentionItems.length === 0 ? (
            <div className="operations-calm-state">
              <span>
                <ShieldCheck size={22} aria-hidden="true" />
              </span>
              <div>
                <strong>No priority exceptions</strong>
                <p>The current overview contains no urgent queue warnings.</p>
              </div>
            </div>
          ) : (
            <ul className="operations-attention-list">
              {attentionItems.map((item) => (
                <li key={item.label}>
                  <Link to={item.destination}>
                    <span>
                      <strong>{item.label}</strong>
                      <small>{item.detail}</small>
                    </span>
                    <b>{item.value.toLocaleString()}</b>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="operations-panel" aria-labelledby="signals-title">
          <div className="operations-section-heading">
            <div>
              <p className="operations-kicker">Service health</p>
              <h2 id="signals-title">System signals</h2>
            </div>
          </div>

          <dl className="operations-signal-list">
            {systemSignals.map((signal) => {
              const Icon = signal.icon;

              return (
                <div key={signal.label}>
                  <dt>
                    <Icon size={17} aria-hidden="true" />
                    {signal.label}
                  </dt>
                  <dd>
                    {formatMetric(signal.value)}
                    {'suffix' in signal ? signal.suffix : ''}
                  </dd>
                </div>
              );
            })}
          </dl>
        </section>
      </div>

      <details className="operations-details">
        <summary>View complete overview metrics</summary>

        <div className="operations-details__sections">
          {data.sections.map((section) => (
            <section key={section.key}>
              <h3>{section.title}</h3>

              <dl>
                {section.metrics.map((item) => (
                  <div key={item.key}>
                    <dt>{item.key.replaceAll('_', ' ')}</dt>
                    <dd>{formatMetric(item)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </details>
    </div>
  );
}
