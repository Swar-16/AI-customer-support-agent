// apps/web/src/features/chat/chat-api.test.ts

import { describe, expect, it, vi } from 'vitest';

import { SafeApiError } from '../../shared/api/safe-error';
import { createTransport } from '../../shared/api/transport';
import { createChatApi } from './chat-api';
import {
  decodeClosedConversation,
  decodeConversationPage,
  decodeMessagePage,
} from './chat-contract';

const CONVERSATION_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';
const OTHER_ID = 'bf187e45-c833-444b-bcc5-39465b2be9fc';

function conversation() {
  return {
    conversation_id: CONVERSATION_ID,
    customer_id: OTHER_ID,
    status: 'open',
    channel: 'web',
    title: null,
    created_at: '2026-09-15T10:00:00Z',
    updated_at: '2026-09-15T10:00:00Z',
    resolved_at: null,
    closed_at: null,
  };
}

function message() {
  return {
    message_id: OTHER_ID,
    conversation_id: CONVERSATION_ID,
    role: 'assistant',
    content: 'A customer-visible response.',
    sequence_number: 2,
    created_at: '2026-09-15T10:01:00Z',
  };
}

function page<T>(items: T[]) {
  return {
    items,
    total: items.length,
    count: items.length,
    limit: 50,
    offset: 0,
    has_more: false,
    next_offset: null,
  };
}

function setup() {
  const fetchImpl = vi.fn<typeof fetch>();

  const api = createChatApi(
    createTransport({
      apiOrigin: 'https://api.example.test',
      getAccessToken: () => 'test-only-token',
      fetchImpl,
    }),
  );

  return { api, fetchImpl };
}

describe('Chat response boundary', () => {
  it('strips unapproved conversation and envelope fields', () => {
    const result = decodeConversationPage({
      ...page([{ ...conversation(), metadata: 'discard-me' }]),
      debug: 'discard-me',
    });

    expect(result.items[0]?.conversation_id).toBe(CONVERSATION_ID);
    expect(JSON.stringify(result)).not.toContain('discard-me');
  });

  it('rejects an unknown conversation status', () => {
    expect(() => decodeConversationPage(page([{ ...conversation(), status: 'unknown' }]))).toThrow(
      SafeApiError,
    );
  });

  it.each(['system', 'tool', 'unknown'])('rejects a non-visible message role: %s', (role) => {
    expect(() => decodeMessagePage(page([{ ...message(), role }]))).toThrow(SafeApiError);
  });

  it('preserves message content without interpreting HTML', () => {
    const content = '<script>example()</script>\n\nCustomer-visible text';
    const result = decodeMessagePage(page([{ ...message(), content }]));

    expect(result.items[0]?.content).toBe(content);
  });

  it('rejects a pagination cursor that cannot advance', () => {
    expect(() =>
      decodeConversationPage({
        ...page([conversation()]),
        has_more: true,
        next_offset: 0,
      }),
    ).toThrow(SafeApiError);
  });

  it('rejects a count that disagrees with the returned items', () => {
    expect(() => decodeMessagePage({ ...page([message()]), count: 2 })).toThrow(SafeApiError);
  });
});

describe('Chat API requests', () => {
  it('creates a web conversation without a caller-supplied owner', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(conversation(), { status: 201 }));

    const result = await api.create('Order question');

    expect(result.ok).toBe(true);
    const request = fetchImpl.mock.calls[0]?.[1];

    expect(request?.method).toBe('POST');
    expect(JSON.parse(String(request?.body))).toEqual({
      channel: 'web',
      title: 'Order question',
    });
  });

  it('serializes supported list filters and pagination', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(page([])));

    await api.list({
      status: 'open',
      channel: 'web',
      limit: 25,
      offset: 50,
    });

    const url = new URL(String(fetchImpl.mock.calls[0]?.[0]));

    expect(url.pathname).toBe('/v1/conversations');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      status: 'open',
      channel: 'web',
      limit: '25',
      offset: '50',
    });
  });

  it('rejects invalid identifiers without sending a request', async () => {
    const { api, fetchImpl } = setup();

    expect((await api.get('../auth/me')).ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('rejects an oversized page request locally', async () => {
    const { api, fetchImpl } = setup();

    expect((await api.history(CONVERSATION_ID, { limit: 201 })).ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('rejects messages belonging to another conversation', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(page([{ ...message(), conversation_id: OTHER_ID }])));

    const result = await api.history(CONVERSATION_ID);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected failure');
    expect(result.error.kind).toBe('invalid-response');
  });

  it('does not repeat an uncertain creation request', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockRejectedValue(new Error('Test connection loss'));

    const result = await api.create();

    expect(result.ok).toBe(false);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});

describe('Conversation closure', () => {
  function closedConversation(changed = true) {
    return {
      conversation_id: CONVERSATION_ID,
      customer_id: OTHER_ID,
      status: 'closed' as const,
      resolved_at: '2026-09-15T10:05:00Z',
      closed_at: '2026-09-15T10:05:00Z',
      updated_at: '2026-09-15T10:05:00Z',
      changed,
    };
  }

  it('posts to the close endpoint without a request body', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(closedConversation()));

    const result = await api.close(CONVERSATION_ID);

    expect(result.ok).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    const call = fetchImpl.mock.calls[0];
    if (!call) throw new Error('Expected one close request.');

    expect(String(call[0])).toBe(
      `https://api.example.test/v1/conversations/${CONVERSATION_ID}/close`,
    );
    expect(call[1]?.method).toBe('POST');
    expect(call[1]?.body).toBeUndefined();
    expect(call[1]?.credentials).toBe('omit');
  });

  it('accepts an already-closed conversation', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(Response.json(closedConversation(false)));

    const result = await api.close(CONVERSATION_ID);

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error('Expected confirmed closure.');

    expect(result.data.status).toBe('closed');
    expect(result.data.changed).toBe(false);
  });

  it('strips properties outside the response contract', () => {
    const result = decodeClosedConversation({
      ...closedConversation(),
      internal_debug: 'discard-me',
    });

    expect(result).not.toHaveProperty('internal_debug');
  });

  it('accepts the nullable resolved_at transport field', () => {
    const result = decodeClosedConversation({
      ...closedConversation(),
      resolved_at: null,
    });

    expect(result.resolved_at).toBeNull();
  });

  it('rejects a response that does not confirm closed status', () => {
    expect(() =>
      decodeClosedConversation({
        ...closedConversation(),
        status: 'resolved',
      }),
    ).toThrow(SafeApiError);
  });

  it('rejects a missing required closure timestamp', () => {
    const { closed_at: omittedTimestamp, ...incomplete } = closedConversation();

    expect(omittedTimestamp).toBeDefined();
    expect(() => decodeClosedConversation(incomplete)).toThrow(SafeApiError);
  });

  it('rejects a response belonging to another conversation', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(
      Response.json({
        ...closedConversation(),
        conversation_id: OTHER_ID,
      }),
    );

    const result = await api.close(CONVERSATION_ID);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected rejected response.');

    expect(result.error.kind).toBe('invalid-response');
  });

  it('rejects an invalid identifier before sending', async () => {
    const { api, fetchImpl } = setup();

    const result = await api.close('../auth/logout');

    expect(result.ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('does not send an already-cancelled request', async () => {
    const { api, fetchImpl } = setup();
    const controller = new AbortController();
    controller.abort();

    const result = await api.close(CONVERSATION_ID, controller.signal);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected cancellation.');

    expect(result.error.kind).toBe('aborted');
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it.each([401, 403, 404, 422, 500])('preserves HTTP %i without retrying', async (status) => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockResolvedValue(
      Response.json(
        {
          error: {
            code: 'TEST_ERROR',
            message: 'Test failure.',
          },
        },
        { status },
      ),
    );

    const result = await api.close(CONVERSATION_ID);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected HTTP failure.');

    expect(result.error.status).toBe(status);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('does not repeat a close request after connection loss', async () => {
    const { api, fetchImpl } = setup();
    fetchImpl.mockRejectedValue(new Error('Simulated connection loss'));

    const result = await api.close(CONVERSATION_ID);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('Expected uncertain outcome.');

    expect(result.error.kind).toBe('network');
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
