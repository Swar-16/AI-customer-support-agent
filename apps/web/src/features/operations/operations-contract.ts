// apps/web/src/features/operations/operations-contract.ts
import { z } from 'zod';

const timestampSchema = z.iso.datetime({ offset: true });

const overviewMetricSchema = z
  .object({
    key: z.string().min(1).max(100),
    value: z.number().finite(),
    unit: z.string().min(1).nullable().default(null),
    metadata: z.record(z.string(), z.unknown()).default({}),
  })
  .strict();

const overviewSectionSchema = z
  .object({
    key: z.string().min(1).max(100),
    title: z.string().min(1).max(200),
    metrics: z.array(overviewMetricSchema),
  })
  .strict()
  .superRefine((section, context) => {
    const keys = new Set<string>();

    section.metrics.forEach((metric, index) => {
      if (keys.has(metric.key)) {
        context.addIssue({
          code: 'custom',
          path: ['metrics', index, 'key'],
          message: 'Metric keys must be unique within a section.',
        });
      }

      keys.add(metric.key);
    });
  });

const dashboardOverviewSchema = z
  .object({
    time_range: z
      .object({
        started_at: timestampSchema,
        ended_at: timestampSchema,
      })
      .strict(),
    generated_at: timestampSchema,
    sections: z.array(overviewSectionSchema),
  })
  .strict()
  .superRefine((overview, context) => {
    const sectionKeys = new Set<string>();

    overview.sections.forEach((section, index) => {
      if (sectionKeys.has(section.key)) {
        context.addIssue({
          code: 'custom',
          path: ['sections', index, 'key'],
          message: 'Overview section keys must be unique.',
        });
      }

      sectionKeys.add(section.key);
    });

    if (
      new Date(overview.time_range.started_at).getTime() >
      new Date(overview.time_range.ended_at).getTime()
    ) {
      context.addIssue({
        code: 'custom',
        path: ['time_range'],
        message: 'The overview time range is invalid.',
      });
    }
  });

export type DashboardOverview = z.infer<typeof dashboardOverviewSchema>;
export type DashboardOverviewSection = DashboardOverview['sections'][number];
export type DashboardOverviewMetric = DashboardOverviewSection['metrics'][number];

export function decodeDashboardOverview(value: unknown): DashboardOverview {
  return dashboardOverviewSchema.parse(value);
}

export function findOverviewMetric(
  overview: DashboardOverview,
  sectionKey: string,
  metricKey: string,
): DashboardOverviewMetric | null {
  const section = overview.sections.find((candidate) => candidate.key === sectionKey);

  return section?.metrics.find((candidate) => candidate.key === metricKey) ?? null;
}
