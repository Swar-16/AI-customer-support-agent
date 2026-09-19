// apps/web/src/features/operations/ticket-api.test.ts
import { describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { createTicketApi } from './ticket-api';

const TICKET_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';

const CONVERSATION_ID = 'bf187e45-c833-444b-bcc5-39465b2be9fc';

const CUSTOMER_ID = '6d6821f3-ccf2-4d6c-8acf-8fdbe847a814';

const AGENT_ID = '2553fe11-ff42-4705-b9f8-b8540b882e96';

function ticket() {
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
  };
}

function page() {
  return {
    items: [ticket()],
    count: 1,
    limit: 20,
    offset: 0,
    has_more: false,
  };
}

function updateResponse() {
  return {
    ticket_id: TICKET_ID,
    ticket_number: 42,
    ticket_reference: 'TKT-000042',
    conversation_id: CONVERSATION_ID,
    customer_id: CUSTOMER_ID,
    previous_status: 'open',
    current_status: 'in_progress',
    priority: 'high',
    category: 'billing',
    assigned_agent_id: AGENT_ID,
    resolution_summary: null,
    row_version: 2,
    assigned_at: '2026-09-19T06:05:00Z',
    resolved_at: null,
    closed_at: null,
    updated_at: '2026-09-19T06:05:00Z',
    changed: true,
  };
}

function commentReceipt() {
  return {
    comment_id: 'cc0d77af-2f31-470f-bd64-a374713b7e8c',
    ticket_id: TICKET_ID,
    author_id: AGENT_ID,
    author_role: 'support_agent',
    visibility: 'internal',
    content: 'Check the payment processor logs.',
    created_at: '2026-09-19T06:06:00Z',
  };
}

function setup() {
  const fetchImpl = vi.fn<typeof fetch>();

  const api = createTicketApi(
    createTransport({
      apiOrigin: 'https://api.example.test',
      getAccessToken: () => 'test-only-token',
      fetchImpl,
    }),
  );

  return { api, fetchImpl };
}

describe('Ticket API', () => {
  it('serializes queue and assignment filters', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockResolvedValue(Response.json(page()));

    await api.list({
      activeOnly: true,
      status: null,
      priority: 'high',
      category: 'billing',
      assignedAgentId: AGENT_ID,
      unassignedOnly: false,
      limit: 20,
      offset: 40,
    });

    const url = new URL(String(fetchImpl.mock.calls[0]?.[0]));

    expect(url.pathname).toBe('/v1/tickets');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      active_only: 'true',
      unassigned_only: 'false',
      priority: 'high',
      category: 'billing',
      assigned_agent_id: AGENT_ID,
      limit: '20',
      offset: '40',
    });
  });

  it('rejects a status filter on the active queue', async () => {
    const { api, fetchImpl } = setup();

    const result = await api.list({
      activeOnly: true,
      status: 'resolved',
      priority: null,
      category: null,
      assignedAgentId: null,
      unassignedOnly: false,
      limit: 20,
      offset: 0,
    });

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('rejects assigned and unassigned filters together', async () => {
    const { api, fetchImpl } = setup();

    const result = await api.list({
      activeOnly: true,
      status: null,
      priority: null,
      category: null,
      assignedAgentId: AGENT_ID,
      unassignedOnly: true,
      limit: 20,
      offset: 0,
    });

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('serializes assignment with optimistic concurrency', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockResolvedValue(Response.json(updateResponse()));

    const result = await api.update(TICKET_ID, {
      expectedRowVersion: 1,
      assignedAgentId: AGENT_ID,
    });

    expect(result.ok).toBe(true);

    const request = fetchImpl.mock.calls[0]?.[1];

    expect(request?.method).toBe('PATCH');
    expect(JSON.parse(String(request?.body))).toEqual({
      expected_row_version: 1,
      assigned_agent_id: AGENT_ID,
    });
  });

  it('rejects resolution without a summary locally', async () => {
    const { api, fetchImpl } = setup();

    const result = await api.update(TICKET_ID, {
      expectedRowVersion: 1,
      targetStatus: 'resolved',
    });

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('serializes a normalized resolution summary', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockResolvedValue(
      Response.json({
        ...updateResponse(),
        current_status: 'resolved',
        assigned_agent_id: null,
        resolution_summary: 'Duplicate payment was reversed.',
        resolved_at: '2026-09-19T06:05:00Z',
      }),
    );

    await api.update(TICKET_ID, {
      expectedRowVersion: 1,
      targetStatus: 'resolved',
      resolutionSummary: '  Duplicate payment was reversed.  ',
    });

    expect(JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body))).toEqual({
      expected_row_version: 1,
      target_status: 'resolved',
      resolution_summary: 'Duplicate payment was reversed.',
    });
  });

  it('serializes an internal ticket note', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockResolvedValue(
      Response.json(commentReceipt(), {
        status: 201,
      }),
    );

    const result = await api.addComment(TICKET_ID, {
      visibility: 'internal',
      content: '  Check the payment processor logs.  ',
    });

    expect(result.ok).toBe(true);

    const request = fetchImpl.mock.calls[0]?.[1];

    expect(request?.method).toBe('POST');
    expect(JSON.parse(String(request?.body))).toEqual({
      visibility: 'internal',
      content: 'Check the payment processor logs.',
    });
  });

  it('rejects an invalid ticket identifier locally', async () => {
    const { api, fetchImpl } = setup();

    const result = await api.get('../tickets');

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
