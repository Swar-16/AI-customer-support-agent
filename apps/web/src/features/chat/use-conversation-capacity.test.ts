// apps/web/src/features/chat/use-conversation-capacity.test.ts
import { describe, expect, it } from 'vitest';

import { conversationCapacity } from './use-conversation-capacity';

describe('conversation capacity', () => {
  it('fits complete rows and does not require a trailing gap', () => {
    expect(conversationCapacity(48, 48, 8)).toBe(1);
    expect(conversationCapacity(103, 48, 8)).toBe(1);
    expect(conversationCapacity(104, 48, 8)).toBe(2);
    expect(conversationCapacity(160, 48, 8)).toBe(3);
  });

  it('reduces capacity when the available space shrinks', () => {
    expect(conversationCapacity(552, 48, 8)).toBe(10);
    expect(conversationCapacity(328, 48, 8)).toBe(6);
  });

  it('respects the API maximum and handles unavailable measurements', () => {
    expect(conversationCapacity(100_000, 48, 8)).toBe(200);
    expect(conversationCapacity(0, 48, 8)).toBe(1);
    expect(conversationCapacity(Number.NaN, 48, 8)).toBe(1);
    expect(conversationCapacity(300, 0, 8)).toBe(1);
  });
});
