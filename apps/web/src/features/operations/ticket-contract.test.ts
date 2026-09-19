// apps/web/src/features/operations/ticket-contract.test.ts
import { describe, expect, it } from 'vitest';

import {
  decodeTicketDetail,
  decodeTicketPage,
  decodeTicketUpdateResponse,
} from './ticket-contract';

const TICKET_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';

const CONVERSATION_ID = 'bf187e45-c833-444b-bcc5-39465b2be9fc';

const CUSTOMER_ID = '6d6821f3-ccf2-4d6c-8acf-8fdbe847a814';

function ticket() {
  return {
    ticket_id: TICKET_ID,
    ticket_number: 42,
    ticket_reference: 'TKT-000042',
    conversation_id: CONVERSATION_ID,
    customer_id: CUSTOMER_ID,
    source: 'customer',
    subject: 'Duplicate payment',
    description: 'The customer was charged twice.',
    category: 'billing',
    priority: 'high',
    status: 'open',
    row_version: 1,
    created_at: '2026-09-19T06:00:00Z',
    updated_at: '2026-09-19T06:00:00Z',
  };
}

describe('ticket contract', () => {
  it('normalizes optional ticket fields', () => {
    const result = decodeTicketPage({
      items: [ticket()],
      count: 1,
      limit: 20,
      offset: 0,
      has_more: false,
    });

    expect(result.items[0]).toMatchObject({
      assigned_agent_id: null,
      resolution_summary: null,
      assigned_at: null,
      resolved_at: null,
      closed_at: null,
      metadata: {},
    });
  });

  it('rejects duplicate tickets in one page', () => {
    expect(() =>
      decodeTicketPage({
        items: [ticket(), ticket()],
        count: 2,
        limit: 20,
        offset: 0,
        has_more: false,
      }),
    ).toThrow();
  });

  it('rejects a comment belonging to another ticket', () => {
    expect(() =>
      decodeTicketDetail({
        ticket: ticket(),
        comments: [
          {
            comment_id: '2553fe11-ff42-4705-b9f8-b8540b882e96',
            ticket_id: 'a73243f1-6b54-4a32-a87f-965f4051c846',
            author_role: 'support_agent',
            visibility: 'customer',
            content: 'We are reviewing the payment.',
            created_at: '2026-09-19T06:05:00Z',
          },
        ],
      }),
    ).toThrow();
  });

  it('decodes internal and customer-visible comments', () => {
    const result = decodeTicketDetail({
      ticket: ticket(),
      comments: [
        {
          comment_id: '2553fe11-ff42-4705-b9f8-b8540b882e96',
          ticket_id: TICKET_ID,
          author_role: 'support_agent',
          visibility: 'customer',
          content: 'We are reviewing the payment.',
          created_at: '2026-09-19T06:05:00Z',
        },
        {
          comment_id: 'cc0d77af-2f31-470f-bd64-a374713b7e8c',
          ticket_id: TICKET_ID,
          author_role: 'admin',
          visibility: 'internal',
          content: 'Check the payment processor logs.',
          created_at: '2026-09-19T06:06:00Z',
        },
      ],
    });

    expect(result.comments.map((comment) => comment.visibility)).toEqual(['customer', 'internal']);
  });

  it('decodes optimistic concurrency information', () => {
    const result = decodeTicketUpdateResponse({
      ticket_id: TICKET_ID,
      ticket_number: 42,
      ticket_reference: 'TKT-000042',
      conversation_id: CONVERSATION_ID,
      customer_id: CUSTOMER_ID,
      previous_status: 'open',
      current_status: 'in_progress',
      priority: 'high',
      category: 'billing',
      row_version: 2,
      updated_at: '2026-09-19T06:10:00Z',
      changed: true,
    });

    expect(result.row_version).toBe(2);
    expect(result.current_status).toBe('in_progress');
    expect(result.assigned_agent_id).toBeNull();
  });
});
