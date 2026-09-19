// apps/web/src/features/operations/escalation-queue.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { TransportContext } from '../../shared/api/transport-context';
import { EscalationQueue } from './escalation-queue';

const auth = vi.hoisted(() => ({
  session: {
    phase: 'authenticated',
    error: null,
    user: {
      id: '6d6821f3-ccf2-4d6c-8acf-8fdbe847a814',
      email: 'agent@example.test',
      display_name: 'Support Agent',
      role: 'support_agent',
      status: 'active',
      created_at: '2026-09-19T05:00:00Z',
    },
  },
}));

vi.mock('../../shared/auth/session-context', () => ({
  useSession: () => auth.session,
}));

const ESCALATION_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';

const SECOND_ESCALATION_ID = '9ba930de-d09f-4ee3-925c-e95c31cc1ac0';

const CONVERSATION_ID = 'bf187e45-c833-444b-bcc5-39465b2be9fc';

function escalation(overrides: Record<string, unknown> = {}) {
  return {
    escalation_id: ESCALATION_ID,
    conversation_id: CONVERSATION_ID,
    ai_run_id: null,
    trigger_message_id: null,
    source: 'manual',
    reason_code: 'CUSTOMER_REQUESTED_HUMAN',
    reason_summary: 'The customer requested assistance from a support agent.',
    priority: 'high',
    status: 'open',
    handoff_summary: 'Review the customer conversation.',
    metadata: {},
    created_at: '2026-09-19T06:00:00Z',
    updated_at: '2026-09-19T06:00:00Z',
    resolved_at: null,
    ...overrides,
  };
}

function page(
  items: ReturnType<typeof escalation>[],
  {
    offset = 0,
    hasMore = false,
  }: {
    readonly offset?: number;
    readonly hasMore?: boolean;
  } = {},
) {
  return {
    items,
    count: items.length,
    limit: 20,
    offset,
    has_more: hasMore,
  };
}

const clients: QueryClient[] = [];

function setup(fetchImplementation: typeof fetch) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Number.POSITIVE_INFINITY,
      },
      mutations: {
        retry: false,
      },
    },
  });

  clients.push(queryClient);

  const fetchImpl = vi.fn(fetchImplementation);

  const transport = createTransport({
    apiOrigin: 'https://api.example.test',
    getAccessToken: () => 'test-only-token',
    fetchImpl,
  });

  const view = render(
    <QueryClientProvider client={queryClient}>
      <TransportContext.Provider value={transport}>
        <EscalationQueue />
      </TransportContext.Provider>
    </QueryClientProvider>,
  );

  return {
    fetchImpl,
    queryClient,
    unmount: view.unmount,
  };
}

afterEach(() => {
  cleanup();

  for (const client of clients) {
    client.clear();
  }

  clients.length = 0;
});

describe('Escalation queue', () => {
  it('loads the active queue without history-only filters', async () => {
    const { fetchImpl } = setup(async () => Response.json(page([escalation()])));

    expect(await screen.findByText('Customer Requested Human')).toBeInTheDocument();

    const firstUrl = new URL(String(fetchImpl.mock.calls[0]?.[0]));

    expect(Object.fromEntries(firstUrl.searchParams)).toEqual({
      active_only: 'true',
      limit: '20',
      offset: '0',
    });

    expect(screen.queryByLabelText('Status')).not.toBeInTheDocument();

    expect(screen.queryByLabelText('Reason code')).not.toBeInTheDocument();
  });

  it('applies history status and reason-code filters', async () => {
    const { fetchImpl } = setup(async () => Response.json(page([escalation()])));

    await screen.findByText('Customer Requested Human');

    fireEvent.click(
      screen.getByRole('button', {
        name: 'History',
      }),
    );

    fireEvent.change(await screen.findByLabelText('Status'), {
      target: {
        value: 'resolved',
      },
    });

    fireEvent.change(screen.getByLabelText('Reason code'), {
      target: {
        value: 'HUMAN_REVIEW_REQUIRED',
      },
    });

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Apply',
      }),
    );

    await waitFor(() => {
      const requestedUrls = fetchImpl.mock.calls.map((call) => new URL(String(call[0])));

      expect(
        requestedUrls.some(
          (url) =>
            url.searchParams.get('active_only') === 'false' &&
            url.searchParams.get('status') === 'resolved' &&
            url.searchParams.get('reason_code') === 'HUMAN_REVIEW_REQUIRED',
        ),
      ).toBe(true);
    });
  });

  it('opens and closes the detail drawer', async () => {
    const { fetchImpl } = setup(async (input) => {
      const url = new URL(String(input));

      if (url.pathname === `/v1/escalations/${ESCALATION_ID}`) {
        return Response.json(escalation());
      }

      return Response.json(page([escalation()]));
    });

    fireEvent.click(
      await screen.findByRole('button', {
        name: /customer requested human/i,
      }),
    );

    expect(
      await screen.findByRole('heading', {
        name: 'Escalation',
      }),
    ).toBeInTheDocument();

    expect(await screen.findByText('Review the customer conversation.')).toBeInTheDocument();

    expect(
      fetchImpl.mock.calls.some((call) => {
        const url = new URL(String(call[0]));

        return url.pathname === `/v1/escalations/${ESCALATION_ID}`;
      }),
    ).toBe(true);

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Close escalation details',
      }),
    );

    expect(
      screen.queryByRole('heading', {
        name: 'Escalation',
      }),
    ).not.toBeInTheDocument();
  });

  it('renders pagination controls only when valid', async () => {
    const { fetchImpl } = setup(async (input) => {
      const url = new URL(String(input));
      const offset = Number(url.searchParams.get('offset') ?? '0');

      if (offset === 20) {
        return Response.json(
          page(
            [
              escalation({
                escalation_id: SECOND_ESCALATION_ID,
                reason_code: 'PAYMENT_REVIEW_REQUIRED',
              }),
            ],
            {
              offset: 20,
              hasMore: false,
            },
          ),
        );
      }

      return Response.json(
        page([escalation()], {
          offset: 0,
          hasMore: true,
        }),
      );
    });

    expect(
      await screen.findByRole('button', {
        name: /customer requested human/i,
      }),
    ).toBeInTheDocument();

    expect(
      screen.queryByRole('button', {
        name: /previous/i,
      }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', {
        name: /next/i,
      }),
    );

    expect(await screen.findByText('Payment Review Required')).toBeInTheDocument();

    expect(
      screen.getByRole('button', {
        name: /previous/i,
      }),
    ).toBeInTheDocument();

    expect(
      screen.queryByRole('button', {
        name: /^next$/i,
      }),
    ).not.toBeInTheDocument();

    expect(
      fetchImpl.mock.calls.some((call) => {
        const url = new URL(String(call[0]));

        return url.searchParams.get('offset') === '20';
      }),
    ).toBe(true);
  });

  it('confirms and submits an in-review transition', async () => {
    let currentStatus = 'open';

    const { fetchImpl } = setup(async (input, request) => {
      const url = new URL(String(input));
      const method = request?.method ?? 'GET';

      if (method === 'PATCH' && url.pathname === `/v1/escalations/${ESCALATION_ID}`) {
        const body = JSON.parse(String(request?.body)) as {
          status: string;
        };

        currentStatus = body.status;

        return Response.json({
          escalation_id: ESCALATION_ID,
          conversation_id: CONVERSATION_ID,
          previous_status: 'open',
          current_status: 'in_review',
          updated_at: '2026-09-19T06:05:00Z',
          resolved_at: null,
          changed: true,
        });
      }

      const currentEscalation = escalation({
        status: currentStatus,
        updated_at: currentStatus === 'open' ? '2026-09-19T06:00:00Z' : '2026-09-19T06:05:00Z',
      });

      if (url.pathname === `/v1/escalations/${ESCALATION_ID}`) {
        return Response.json(currentEscalation);
      }

      return Response.json(page([currentEscalation]));
    });

    fireEvent.click(
      await screen.findByRole('button', {
        name: /customer requested human/i,
      }),
    );

    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Start review',
      }),
    );

    expect(
      screen.getByRole('dialog', {
        name: 'Mark as in review?',
      }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Confirm in review',
      }),
    );

    expect(await screen.findByText('Escalation moved to in review.')).toBeInTheDocument();

    const patchRequest = fetchImpl.mock.calls.find(([input, request]) => {
      const url = new URL(String(input));

      return request?.method === 'PATCH' && url.pathname === `/v1/escalations/${ESCALATION_ID}`;
    });

    expect(patchRequest).toBeDefined();

    expect(JSON.parse(String(patchRequest?.[1]?.body))).toEqual({
      status: 'in_review',
    });
  });

  it('closes the confirmation with Escape without mutating', async () => {
    const { fetchImpl } = setup(async (input) => {
      const url = new URL(String(input));

      if (url.pathname === `/v1/escalations/${ESCALATION_ID}`) {
        return Response.json(escalation());
      }

      return Response.json(page([escalation()]));
    });

    fireEvent.click(
      await screen.findByRole('button', {
        name: /customer requested human/i,
      }),
    );

    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Start review',
      }),
    );

    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.keyDown(document, {
      key: 'Escape',
    });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    expect(fetchImpl.mock.calls.some((call) => call[1]?.method === 'PATCH')).toBe(false);
  });
});
