// apps/web/src/features/operations/operations-overview.tsx
import { useState } from 'react';
import { Link } from 'react-router';
import {
  Activity,
  ArrowUpRight,
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
import { DashboardJellySwitch } from './dashboard-jelly-switch';

const windowLabels: Record<OverviewWindow, string> = {
  '24h': '24 hours',
  '7d': '7 days',
  '30d': '30 days',
};

type SpotlightTone = 'escalation' | 'ticket' | 'feedback' | 'ai';
type AttentionTone = 'urgent' | 'high' | 'ticket' | 'knowledge';
type SignalTone = 'api' | 'ai' | 'retrieval' | 'feedback';

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
  if (value === null || value.metadata.has_data === false) {
    return '—';
  }

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
    <section
      className="operations-dashboard-loader"
      role="status"
      aria-live="polite"
      aria-label="Loading operations dashboard"
    >
      <div className="operations-dashboard-loader__visual" aria-hidden="true">
        <span className="operations-dashboard-loader__orbit operations-dashboard-loader__orbit--one" />
        <span className="operations-dashboard-loader__orbit operations-dashboard-loader__orbit--two" />

        <span className="operations-dashboard-loader__core">
          <Activity size={27} />
        </span>
      </div>

      <div className="operations-dashboard-loader__copy">
        <p className="operations-kicker">Operations intelligence</p>
        <h2>Preparing your operational pulse</h2>
        <p>Gathering queue health, AI activity, customer feedback, and knowledge signals.</p>
      </div>

      <div className="operations-dashboard-loader__signals" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
      </div>
    </section>
  );
}

interface AttentionItem {
  readonly label: string;
  readonly detail: string;
  readonly value: number;
  readonly destination: string;
  readonly tone: AttentionTone;
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

  const spotlightCards: ReadonlyArray<{
    readonly label: string;
    readonly value: DashboardOverviewMetric | null;
    readonly icon: typeof ShieldCheck;
    readonly destination: string;
    readonly tone: SpotlightTone;
    readonly action: string;
  }> = [
    {
      label: 'Open escalations',
      value: metric(data, 'escalations', 'open_escalations'),
      icon: ShieldCheck,
      destination: '/operations/escalations?view=active',
      tone: 'escalation',
      action: 'Review queue',
    },
    {
      label: 'Active tickets',
      value: metric(data, 'tickets', 'active_tickets'),
      icon: TicketCheck,
      destination: '/operations/tickets?view=active',
      tone: 'ticket',
      action: 'Open tickets',
    },
    {
      label: 'Feedback awaiting review',
      value: metric(data, 'feedback', 'pending_feedback'),
      icon: Star,
      destination: '/operations/feedback?tab=pending',
      tone: 'feedback',
      action: 'Review feedback',
    },
    {
      label: 'AI runs in progress',
      value: metric(data, 'ai_runs', 'running_runs'),
      icon: Bot,
      destination: '/operations/ai-activity',
      tone: 'ai',
      action: 'View activity',
    },
  ];

  const attentionItems = (
    [
      {
        label: 'Urgent escalations',
        detail: 'Require immediate support review',
        value: metricNumber(data, 'escalations', 'urgent_priority_active'),
        destination: '/operations/escalations?view=active&priority=urgent',
        tone: 'urgent',
      },
      {
        label: 'High-priority escalations',
        detail: 'Active high-priority customer cases',
        value: metricNumber(data, 'escalations', 'high_priority_active'),
        destination: '/operations/escalations?view=active&priority=high',
        tone: 'high',
      },
      {
        label: 'Unassigned tickets',
        detail: 'Active tickets without an owner',
        value: metricNumber(data, 'tickets', 'unassigned_active_tickets'),
        destination: '/operations/tickets?view=active&scope=unassigned',
        tone: 'ticket',
      },
      {
        label: 'Failed knowledge versions',
        detail: 'Knowledge processing requires attention',
        value: metricNumber(data, 'knowledge', 'failed_versions'),
        destination: '/operations/knowledge-health',
        tone: 'knowledge',
      },
    ] satisfies AttentionItem[]
  ).filter((item) => item.value > 0);

  const systemSignals: ReadonlyArray<{
    readonly label: string;
    readonly detail: string;
    readonly value: DashboardOverviewMetric | null;
    readonly icon: typeof Activity;
    readonly suffix: string;
    readonly destination: string;
    readonly tone: SignalTone;
  }> = [
    {
      label: 'API error rate',
      detail: 'Request reliability',
      value: metric(data, 'api', 'error_rate'),
      icon: Activity,
      suffix: '',
      destination: '/operations/ai-activity',
      tone: 'api',
    },
    {
      label: 'AI success rate',
      detail: 'Completed AI runs',
      value: metric(data, 'ai_runs', 'success_rate'),
      icon: Bot,
      suffix: '',
      destination: '/operations/ai-activity',
      tone: 'ai',
    },
    {
      label: 'Retrieval zero-result rate',
      detail: 'Searches without evidence',
      value: metric(data, 'retrieval', 'zero_result_rate'),
      icon: CircleAlert,
      suffix: '',
      destination: '/operations/ai-activity',
      tone: 'retrieval',
    },
    {
      label: 'Average feedback rating',
      detail: 'Customer response score',
      value: metric(data, 'feedback', 'average_rating'),
      icon: Star,
      suffix: ' / 5',
      destination: '/operations/feedback?tab=reviewed',
      tone: 'feedback',
    },
  ];

  const isUpdating = overview.isFetching && overview.data !== undefined;

  return (
    <div
      className={`operations-overview${isUpdating ? ' is-updating' : ''}`}
      aria-busy={isUpdating}
    >
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
          <DashboardJellySwitch
            label="Overview period"
            value={window}
            options={overviewWindows.map((candidate) => ({
              value: candidate,
              label: windowLabels[candidate],
            }))}
            onChange={setWindow}
          />

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

      {isUpdating ? (
        <div className="operations-overview-update" role="status" aria-live="polite">
          <span className="operations-overview-update__animation" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>

          <span>Updating the {windowLabels[window]} view…</span>
        </div>
      ) : null}

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
              <Link
                className={`operations-stat-card operations-stat-card--${card.tone}`}
                to={card.destination}
                key={card.label}
                aria-label={`${card.label}: ${formatMetric(card.value)}. ${card.action}`}
              >
                <span className="operations-stat-card__icon">
                  <Icon size={20} aria-hidden="true" />
                </span>

                <span className="operations-stat-card__value">{formatMetric(card.value)}</span>

                <span className="operations-stat-card__label">{card.label}</span>

                <span className="operations-stat-card__action">
                  {card.action}
                  <ArrowUpRight size={15} aria-hidden="true" />
                </span>
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
                <p>There are no urgent queue warnings in this period.</p>
              </div>
            </div>
          ) : (
            <ul className="operations-attention-list">
              {attentionItems.map((item) => (
                <li
                  className={`operations-attention-item operations-attention-item--${item.tone}`}
                  key={item.label}
                >
                  <Link to={item.destination}>
                    <span>
                      <strong>{item.label}</strong>
                      <small>{item.detail}</small>
                    </span>

                    <span className="operations-attention-item__end">
                      <b>{item.value.toLocaleString()}</b>
                      <ArrowUpRight size={16} aria-hidden="true" />
                    </span>
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

          <ul className="operations-signal-list">
            {systemSignals.map((signal) => {
              const Icon = signal.icon;

              return (
                <li
                  className={`operations-signal operations-signal--${signal.tone}`}
                  key={signal.label}
                >
                  <Link to={signal.destination}>
                    <span className="operations-signal__identity">
                      <span className="operations-signal__icon">
                        <Icon size={17} aria-hidden="true" />
                      </span>

                      <span>
                        <strong>{signal.label}</strong>
                        <small>{signal.detail}</small>
                      </span>
                    </span>

                    <span className="operations-signal__value">
                      {formatMetric(signal.value)}
                      {signal.suffix}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
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
