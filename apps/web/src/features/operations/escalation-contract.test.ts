// apps/web/src/features/operations/escalation-contract.test.ts
import { describe, expect, it } from 'vitest';

import {
  decodeEscalation,
  decodeEscalationPage,
  decodeEscalationUpdate,
} from './escalation-contract';

const escalation = {
  escalation_id: '01994895-3570-7e31-82a0-cf96cdd81a62',
  conversation_id: '01994895-3570-7e31-82a0-cf96cdd81a63',
  source: 'manual',
  reason_code: 'CUSTOMER_REQUESTED_HUMAN',
  reason_summary: 'The customer requested help from a support agent.',
  priority: 'high',
  status: 'open',
  handoff_summary: 'Review the customer conversation.',
  metadata: {
    channel: 'web',
  },
  created_at: '2026-09-19T06:00:00+00:00',
  updated_at: '2026-09-19T06:00:00+00:00',
};

describe('escalation contract', () => {
  it('normalizes optional escalation fields', () => {
    expect(decodeEscalation(escalation)).toMatchObject({
      ai_run_id: null,
      trigger_message_id: null,
      resolved_at: null,
    });
  });

  it('decodes a valid escalation page', () => {
    const result = decodeEscalationPage({
      items: [escalation],
      count: 1,
      limit: 20,
      offset: 0,
      has_more: false,
    });

    expect(result.items).toHaveLength(1);
    expect(result.items[0]?.priority).toBe('high');
  });

  it('rejects duplicate escalation identifiers', () => {
    expect(() =>
      decodeEscalationPage({
        items: [escalation, escalation],
        count: 2,
        limit: 20,
        offset: 0,
        has_more: false,
      }),
    ).toThrow();
  });

  it('rejects unknown escalation values', () => {
    expect(() =>
      decodeEscalation({
        ...escalation,
        priority: 'catastrophic',
      }),
    ).toThrow();
  });

  it('decodes a lifecycle update', () => {
    expect(
      decodeEscalationUpdate({
        escalation_id: escalation.escalation_id,
        conversation_id: escalation.conversation_id,
        previous_status: 'open',
        current_status: 'in_review',
        updated_at: '2026-09-19T06:05:00+00:00',
        changed: true,
      }),
    ).toMatchObject({
      previous_status: 'open',
      current_status: 'in_review',
      resolved_at: null,
      changed: true,
    });
  });
});
