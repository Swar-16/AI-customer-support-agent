// apps/web/src/features/operations\ticket-actions.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { TransportContext } from '../../shared/api/transport-context';
import type { Ticket } from './ticket-contract';
import { TicketActions } from './ticket-actions';

const auth = vi.hoisted(() => ({
  session: {
    phase: 'authenticated',
    error: null,
    user: {
      id: '2553fe11-ff42-4705-b9f8-b8540b882e96',
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

const TICKET_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';

const CONVERSATION_ID = 'bf187e45-c833-444b-bcc5-39465b2be9fc';

const CUSTOMER_ID = '6d6821f3-ccf2-4d6c-8acf-8fdbe847a814';

const TRACE_ID = '8cc30db4-c725-4567-a413-9b874e868918';

function ticket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    ticket_id: TICKET_ID,
    ticket_number: 42,
    ticket_reference: 'TKT-000042',
    conversation_id: CONVERSATION_ID,
    customer_id: CUSTOMER_ID,
    source_message_id: null,
    escalation_id: null,
    assigned_agent_id: null,
    source: 'customer',
    subject: 'Duplicate payment',
    description: 'The customer was charged twice.',
    category: 'billing',
    priority: 'high',
    status: 'open',
    resolution_summary: null,
    metadata: {},
    row_version: 1,
    created_at: '2026-09-19T06:00:00Z',
    updated_at: '2026-09-19T06:00:00Z',
    assigned_at: null,
    resolved_at: null,
    closed_at: null,
    ...overrides,
  };
}

function updateResponse(overrides: Record<string, unknown> = {}) {
  return {
    ticket_id: TICKET_ID,
    ticket_number: 42,
    ticket_reference: 'TKT-000042',
    conversation_id: CONVERSATION_ID,
    customer_id: CUSTOMER_ID,
    previous_status: 'open',
    current_status: 'open',
    priority: 'high',
    category: 'billing',
    assigned_agent_id: auth.session.user.id,
    resolution_summary: null,
    row_version: 2,
    assigned_at: '2026-09-19T06:05:00Z',
    resolved_at: null,
    closed_at: null,
    updated_at: '2026-09-19T06:05:00Z',
    changed: true,
    ...overrides,
  };
}

const clients: QueryClient[] = [];

function setup(currentTicket: Ticket, fetchImplementation: typeof fetch) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
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

  render(
    <QueryClientProvider client={queryClient}>
      <TransportContext.Provider value={transport}>
        <TicketActions ticket={currentTicket} currentOperatorId={auth.session.user.id} />
      </TransportContext.Provider>
    </QueryClientProvider>,
  );

  return { fetchImpl, queryClient };
}

afterEach(() => {
  cleanup();

  for (const client of clients) {
    client.clear();
  }

  clients.length = 0;
});

describe('ticket actions', () => {
  it('assigns an unassigned ticket to the current operator', async () => {
    const { fetchImpl } = setup(ticket(), async () => Response.json(updateResponse()));

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Assign to me',
      }),
    );

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    expect(JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body))).toEqual({
      expected_row_version: 1,
      assigned_agent_id: auth.session.user.id,
    });

    expect(await screen.findByText('The ticket is now assigned to you.')).toBeInTheDocument();
  });

  it('does not submit a resolution without a summary', async () => {
    const { fetchImpl } = setup(
      ticket({
        status: 'in_progress',
      }),
      async () =>
        Response.json(
          updateResponse({
            previous_status: 'in_progress',
            current_status: 'resolved',
            resolution_summary: 'Duplicate payment was reversed.',
            resolved_at: '2026-09-19T06:05:00Z',
          }),
        ),
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Resolve',
      }),
    );

    const confirm = screen.getByRole('button', {
      name: 'Confirm resolved',
    });

    expect(confirm).toBeDisabled();

    fireEvent.click(confirm);

    expect(fetchImpl).not.toHaveBeenCalled();

    fireEvent.change(
      screen.getByRole('textbox', {
        name: /resolution summary/i,
      }),
      {
        target: {
          value: 'Duplicate payment was reversed.',
        },
      },
    );

    expect(confirm).toBeEnabled();

    fireEvent.click(confirm);

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    expect(JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body))).toEqual({
      expected_row_version: 1,
      target_status: 'resolved',
      resolution_summary: 'Duplicate payment was reversed.',
    });
  });

  it('submits classification changes together', async () => {
    const { fetchImpl } = setup(ticket(), async () =>
      Response.json(
        updateResponse({
          priority: 'urgent',
          category: 'refund',
        }),
      ),
    );

    fireEvent.change(screen.getByLabelText('Priority'), {
      target: {
        value: 'urgent',
      },
    });

    fireEvent.change(screen.getByLabelText('Category'), {
      target: {
        value: 'refund',
      },
    });

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Apply changes',
      }),
    );

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    expect(JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body))).toEqual({
      expected_row_version: 1,
      priority: 'urgent',
      category: 'refund',
    });
  });

  it('surfaces stale row-version conflicts safely', async () => {
    setup(ticket(), async () =>
      Response.json(
        {
          error: {
            code: 'TICKET_CONCURRENT_UPDATE',
            message: 'The ticket changed before the update was applied.',
            trace_id: TRACE_ID,
          },
        },
        {
          status: 409,
          headers: {
            'X-Trace-ID': TRACE_ID,
          },
        },
      ),
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Assign to me',
      }),
    );

    expect(await screen.findByText(/this ticket changed after it was opened/i)).toBeInTheDocument();
  });

  it('prevents closed-ticket edits until it is reopened', () => {
    setup(
      ticket({
        status: 'closed',
        resolution_summary: 'Duplicate payment was reversed.',
        resolved_at: '2026-09-19T06:05:00Z',
        closed_at: '2026-09-19T06:10:00Z',
      }),
      async () => Response.json(updateResponse()),
    );

    expect(
      screen.getByRole('button', {
        name: 'Assign to me',
      }),
    ).toBeDisabled();

    expect(
      screen.getByRole('button', {
        name: 'Apply changes',
      }),
    ).toBeDisabled();

    expect(
      screen.getByRole('button', {
        name: 'Reopen ticket',
      }),
    ).toBeEnabled();

    expect(screen.getByText(/must be reopened before their assignment/i)).toBeInTheDocument();
  });
});
