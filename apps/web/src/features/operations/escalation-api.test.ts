// apps/web/src/features/operations/escalation-api.test.ts
import { describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { createEscalationApi } from './escalation-api';

const ESCALATION_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';

const CONVERSATION_ID = 'bf187e45-c833-444b-bcc5-39465b2be9fc';

function escalation() {
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
  };
}

function page() {
  return {
    items: [escalation()],
    count: 1,
    limit: 20,
    offset: 0,
    has_more: false,
  };
}

function setup() {
  const fetchImpl = vi.fn<typeof fetch>();

  const api = createEscalationApi(
    createTransport({
      apiOrigin: 'https://api.example.test',
      getAccessToken: () => 'test-only-token',
      fetchImpl,
    }),
  );

  return { api, fetchImpl };
}

describe('Escalation API', () => {
  it('serializes an active priority queue request', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockResolvedValue(Response.json(page()));

    const result = await api.list({
      activeOnly: true,
      status: null,
      priority: 'urgent',
      reasonCode: null,
      limit: 20,
      offset: 40,
    });

    expect(result.ok).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    const url = new URL(String(fetchImpl.mock.calls[0]?.[0]));

    expect(url.pathname).toBe('/v1/escalations');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      active_only: 'true',
      priority: 'urgent',
      limit: '20',
      offset: '40',
    });
  });

  it('serializes supported history filters', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockResolvedValue(Response.json(page()));

    await api.list({
      activeOnly: false,
      status: 'resolved',
      priority: 'high',
      reasonCode: 'HUMAN_REVIEW_REQUIRED',
      limit: 50,
      offset: 0,
    });

    const url = new URL(String(fetchImpl.mock.calls[0]?.[0]));

    expect(Object.fromEntries(url.searchParams)).toEqual({
      active_only: 'false',
      status: 'resolved',
      priority: 'high',
      reason_code: 'HUMAN_REVIEW_REQUIRED',
      limit: '50',
      offset: '0',
    });
  });

  it('rejects incompatible active-only filters locally', async () => {
    const { api, fetchImpl } = setup();

    const result = await api.list({
      activeOnly: true,
      status: 'resolved',
      priority: null,
      reasonCode: null,
      limit: 20,
      offset: 0,
    });

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('rejects invalid identifiers without requesting them', async () => {
    const { api, fetchImpl } = setup();

    const result = await api.get('../auth/me');

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('retrieves one escalation by its validated identifier', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockResolvedValue(Response.json(escalation()));

    const result = await api.get(ESCALATION_ID);

    expect(result.ok).toBe(true);

    const url = new URL(String(fetchImpl.mock.calls[0]?.[0]));

    expect(url.pathname).toBe(`/v1/escalations/${ESCALATION_ID}`);
    expect(fetchImpl.mock.calls[0]?.[1]?.method).toBe('GET');
  });

  it('sends a lifecycle transition through PATCH', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockResolvedValue(
      Response.json({
        escalation_id: ESCALATION_ID,
        conversation_id: CONVERSATION_ID,
        previous_status: 'open',
        current_status: 'in_review',
        updated_at: '2026-09-19T06:05:00Z',
        resolved_at: null,
        changed: true,
      }),
    );

    const result = await api.updateStatus(ESCALATION_ID, 'in_review');

    expect(result.ok).toBe(true);

    const request = fetchImpl.mock.calls[0]?.[1];

    expect(request?.method).toBe('PATCH');
    expect(JSON.parse(String(request?.body))).toEqual({
      status: 'in_review',
    });
  });

  it('does not retry an uncertain lifecycle request', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockRejectedValue(new Error('Test connection failure'));

    const result = await api.updateStatus(ESCALATION_ID, 'resolved');

    expect(result.ok).toBe(false);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
