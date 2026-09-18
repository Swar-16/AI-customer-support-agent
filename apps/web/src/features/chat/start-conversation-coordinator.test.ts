// apps/web/src/features/chat/start-conversation-coordinator.test.ts
import { describe, expect, it, vi } from 'vitest';

import { SafeApiError } from '../../shared/api/safe-error';

import type { StartConversationApi } from './start-conversation-api';
import { createStartConversationCoordinator } from './start-conversation-coordinator';

type ApiResult = Awaited<ReturnType<StartConversationApi['start']>>;

const KEY = 'cc757b36-55b6-4449-8137-78de02af6ff4';
const CONVERSATION_ID = '11111111-1111-4111-8111-111111111111';
const START_ID = '22222222-2222-4222-8222-222222222222';

function processing(): ApiResult {
  return {
    ok: true,
    traceId: null,
    data: {
      kind: 'processing',
      retryAfterMs: 2_000,
      data: {
        conversation_id: CONVERSATION_ID,
        start_request_id: START_ID,
        idempotency_status: 'processing',
        retry_after_seconds: 2,
      },
    },
  };
}

function harness() {
  let time = 0;
  const start = vi.fn<StartConversationApi['start']>();
  start.mockResolvedValue(processing());

  const createKey = vi.fn(() => KEY);
  const coordinator = createStartConversationCoordinator({
    api: { start },
    createKey,
    now: () => time,
  });

  return {
    coordinator,
    start,
    createKey,
    advance(ms: number) {
      time += ms;
    },
  };
}

describe('start conversation coordinator', () => {
  it('does not send a request or generate a key for an empty draft', async () => {
    const { coordinator, start, createKey } = harness();

    await coordinator.submit('   ');

    expect(coordinator.getSnapshot()).toEqual({ phase: 'idle' });
    expect(start).not.toHaveBeenCalled();
    expect(createKey).not.toHaveBeenCalled();
  });

  it('blocks duplicate submission while the request is pending', async () => {
    const { coordinator, start } = harness();

    let resolveRequest!: (value: ApiResult) => void;
    start.mockImplementationOnce(
      () =>
        new Promise<ApiResult>((resolve) => {
          resolveRequest = resolve;
        }),
    );

    const first = coordinator.submit('Hello');
    await coordinator.submit('Hello');

    expect(start).toHaveBeenCalledTimes(1);

    resolveRequest(processing());
    await first;
  });

  it('waits before recovery and reuses the exact accepted input', async () => {
    const { coordinator, start, createKey, advance } = harness();

    await coordinator.submit('  Hello  ');
    await coordinator.recover();
    expect(start).toHaveBeenCalledTimes(1);

    advance(2_000);
    await coordinator.recover();

    expect(start).toHaveBeenCalledTimes(2);
    expect(start.mock.calls[0]?.[0]).toEqual({
      message: 'Hello',
      idempotencyKey: KEY,
    });
    expect(start.mock.calls[1]?.[0]).toEqual(start.mock.calls[0]?.[0]);
    expect(createKey).toHaveBeenCalledTimes(1);
  });

  it('does not replace an unresolved submission with edited text', async () => {
    const { coordinator, start, createKey } = harness();

    await coordinator.submit('First message');
    await coordinator.submit('Changed message');

    expect(start).toHaveBeenCalledTimes(1);
    expect(createKey).toHaveBeenCalledTimes(1);
  });

  it('bounds recovery to five total attempts', async () => {
    const { coordinator, start, advance } = harness();

    await coordinator.submit('Hello');

    for (let attempt = 0; attempt < 8; attempt += 1) {
      advance(2_000);
      await coordinator.recover();
    }

    expect(start).toHaveBeenCalledTimes(5);
    expect(coordinator.getSnapshot()).toMatchObject({
      phase: 'processing',
      attemptsRemaining: 0,
    });
  });

  it('permits explicit same-key recovery after an uncertain network outcome', async () => {
    const { coordinator, start, advance } = harness();
    start.mockResolvedValueOnce({
      ok: false,
      error: SafeApiError.fromLocal('network'),
      retryAfterMs: null,
    });

    await coordinator.submit('Hello');

    expect(coordinator.getSnapshot()).toMatchObject({
      phase: 'uncertain',
    });

    advance(1_000);
    await coordinator.recover();

    expect(start).toHaveBeenCalledTimes(2);
    expect(start.mock.calls[1]?.[0]).toEqual(start.mock.calls[0]?.[0]);
  });

  it.each([401, 403, 409, 413, 415, 422])('blocks recovery for HTTP %i', async (status) => {
    const { coordinator, start, advance } = harness();
    start.mockResolvedValueOnce({
      ok: false,
      error: SafeApiError.fromHttp(status, null),
      retryAfterMs: null,
    });

    await coordinator.submit('Hello');
    advance(10_000);
    await coordinator.recover();

    expect(coordinator.getSnapshot()).toMatchObject({
      phase: 'blocked',
    });
    expect(start).toHaveBeenCalledTimes(1);
  });

  it('aborts on disposal and ignores a late result', async () => {
    const { coordinator, start } = harness();

    let resolveRequest!: (value: ApiResult) => void;
    start.mockImplementationOnce(
      () =>
        new Promise<ApiResult>((resolve) => {
          resolveRequest = resolve;
        }),
    );

    const pending = coordinator.submit('Hello');
    const signal = start.mock.calls[0]?.[1];

    coordinator.dispose();

    expect(signal?.aborted).toBe(true);

    resolveRequest(processing());
    await pending;

    expect(coordinator.getSnapshot()).toEqual({ phase: 'disposed' });
  });

  it('rejects a recovery response identifying a different conversation', async () => {
    const { coordinator, start, advance } = harness();

    await coordinator.submit('Hello');

    start.mockResolvedValueOnce({
      ok: true,
      traceId: null,
      data: {
        kind: 'processing',
        retryAfterMs: 2_000,
        data: {
          conversation_id: '33333333-3333-4333-8333-333333333333',
          start_request_id: START_ID,
          idempotency_status: 'processing',
          retry_after_seconds: 2,
        },
      },
    });

    advance(2_000);
    await coordinator.recover();

    expect(coordinator.getSnapshot()).toMatchObject({
      phase: 'blocked',
    });
  });
});
