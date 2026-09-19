// apps/web/src/features/operations/operations-contract.test.ts
import { describe, expect, it } from 'vitest';

import { decodeDashboardOverview, findOverviewMetric } from './operations-contract';

const validOverview = {
  time_range: {
    started_at: '2026-09-17T12:00:00+00:00',
    ended_at: '2026-09-18T12:00:00+00:00',
  },
  generated_at: '2026-09-18T12:00:01+00:00',
  sections: [
    {
      key: 'tickets',
      title: 'Tickets',
      metrics: [
        {
          key: 'active',
          value: 4,
          unit: null,
          metadata: {},
        },
      ],
    },
  ],
};

describe('operations overview contract', () => {
  it('decodes an overview and locates a metric', () => {
    const result = decodeDashboardOverview(validOverview);

    expect(findOverviewMetric(result, 'tickets', 'active')).toMatchObject({
      value: 4,
    });
  });

  it('supplies safe defaults for optional metric presentation data', () => {
    const result = decodeDashboardOverview({
      ...validOverview,
      sections: [
        {
          key: 'tickets',
          title: 'Tickets',
          metrics: [{ key: 'active', value: 4 }],
        },
      ],
    });

    expect(result.sections[0]?.metrics[0]).toMatchObject({
      unit: null,
      metadata: {},
    });
  });

  it('rejects duplicate metric keys', () => {
    expect(() =>
      decodeDashboardOverview({
        ...validOverview,
        sections: [
          {
            key: 'tickets',
            title: 'Tickets',
            metrics: [
              { key: 'active', value: 4 },
              { key: 'active', value: 7 },
            ],
          },
        ],
      }),
    ).toThrow();
  });

  it('rejects a reversed time range', () => {
    expect(() =>
      decodeDashboardOverview({
        ...validOverview,
        time_range: {
          started_at: '2026-09-19T12:00:00+00:00',
          ended_at: '2026-09-18T12:00:00+00:00',
        },
      }),
    ).toThrow();
  });
});
