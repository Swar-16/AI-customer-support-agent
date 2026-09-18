// apps/web/src/features/chat/customer-escalation-api.test.ts
import { describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { createCustomerEscalationApi, type CustomerEscalation } from './customer-escalation-api';

const CONVERSATION_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';
const ESCALATION_ID = '458890db-2435-4267-895d-9aa795dcd8cb';

function escalation(overrides: Partial<CustomerEscalation> = {}): CustomerEscalation {
  return {
    escalation_id: ESCALATION_ID,
    conversation_id: CONVERSATION_ID,
    status: 'open',
    priority: 'normal',
    created_at: '2026-09-15T10:00:00Z',
    updated_at: '2026-09-15T10:00:00Z',
    resolved_at: null,
    ...overrides,
  };
}

function setup() {
  const fetchImpl = vi.fn<typeof fetch>();

  const api = createCustomerEscalationApi(
    createTransport({
      apiOrigin: 'https://api.example.test',
      getAccessToken: () => 'test-only-token',
      fetchImpl,
    }),
  );

  return { api, fetchImpl };
}

describe('Customer escalation API', () => {
  it('uses the customer status endpoint without a body or pagination', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(escalation()));

    const result = await api.get(CONVERSATION_ID);

    expect(result.ok).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    const call = fetchImpl.mock.calls[0];
    if (!call) throw new Error('Expected a request.');

    expect(String(call[0])).toBe(
      `https://api.example.test/v1/conversations/${CONVERSATION_ID}/escalation-status`,
    );
    expect(call[1]?.method).toBe('GET');
    expect(call[1]?.body).toBeUndefined();
    expect(call[1]?.credentials).toBe('omit');
  });

  it('strips internal fields before returning data to the UI', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockResolvedValue(
      Response.json({
        ...escalation(),
        ai_run_id: 'internal-test-value',
        trigger_message_id: 'internal-test-value',
        reason_code: 'INTERNAL_TEST_REASON',
        reason_summary: 'Internal test summary',
        handoff_summary: 'Internal test handoff',
        source: 'guardrail',
        metadata: { debug: 'Internal test metadata' },
      }),
    );

    const result = await api.get(CONVERSATION_ID);

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error('Expected successful adaptation.');

    expect(result.data).toEqual(escalation());
  });

  it.each(['open', 'in_review', 'resolved', 'dismissed'] as const)(
    'accepts the confirmed status %s',
    async (status) => {
      const { api, fetchImpl } = setup();
      fetchImpl.mockResolvedValue(Response.json(escalation({ status })));

      const result = await api.get(CONVERSATION_ID);

      expect(result.ok).toBe(true);
      if (!result.ok) throw new Error('Expected successful adaptation.');

      expect(result.data.status).toBe(status);
    },
  );

  it.each(['low', 'normal', 'high', 'urgent'] as const)(
    'accepts the confirmed priority %s',
    async (priority) => {
      const { api, fetchImpl } = setup();
      fetchImpl.mockResolvedValue(Response.json(escalation({ priority })));

      const result = await api.get(CONVERSATION_ID);

      expect(result.ok).toBe(true);
      if (!result.ok) throw new Error('Expected successful adaptation.');

      expect(result.data.priority).toBe(priority);
    },
  );

  it.each([
    { status: 'assigned' },
    { priority: 'critical' },
    { updated_at: 'not-a-timestamp' },
    { escalation_id: 'not-a-uuid' },
  ])('rejects unsupported response values: %j', async (override) => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json({ ...escalation(), ...override }));

    const result = await api.get(CONVERSATION_ID);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected rejected response.');

    expect(result.error.kind).toBe('invalid-response');
  });

  it('normalizes an omitted optional resolved_at to null', async () => {
    const { api, fetchImpl } = setup();

    const payload = {
      escalation_id: ESCALATION_ID,
      conversation_id: CONVERSATION_ID,
      status: 'open',
      priority: 'normal',
      created_at: '2026-09-15T10:00:00Z',
      updated_at: '2026-09-15T10:00:00Z',
    };

    fetchImpl.mockResolvedValue(Response.json(payload));

    const result = await api.get(CONVERSATION_ID);

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error('Expected successful adaptation.');

    expect(result.data.resolved_at).toBeNull();
  });

  it('rejects a response for another conversation', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockResolvedValue(Response.json(escalation({ conversation_id: ESCALATION_ID })));

    const result = await api.get(CONVERSATION_ID);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected rejected response.');

    expect(result.error.kind).toBe('invalid-response');
  });

  it('preserves 404 instead of inventing an empty success', async () => {
    const { api, fetchImpl } = setup();

    fetchImpl.mockResolvedValue(
      Response.json(
        {
          error: {
            code: 'TEST_NOT_FOUND',
            message: 'Unavailable.',
          },
        },
        { status: 404 },
      ),
    );

    const result = await api.get(CONVERSATION_ID);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected unavailable result.');

    expect(result.error.status).toBe(404);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('rejects an invalid conversation ID without a request', async () => {
    const { api, fetchImpl } = setup();

    const result = await api.get('../escalations');

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('honors cancellation before starting a request', async () => {
    const { api, fetchImpl } = setup();
    const controller = new AbortController();
    controller.abort();

    const result = await api.get(CONVERSATION_ID, controller.signal);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected cancellation.');

    expect(result.error.kind).toBe('aborted');
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
