// apps/web/src/features/chat/outgoing-turn.test.tsx
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { OutgoingTurn } from './outgoing-turn';
import { shouldShowOutgoing, type OutgoingMessage } from './outgoing-message';

afterEach(cleanup);
const message: OutgoingMessage = {
  localId: 'local-1',
  content: 'Where is my refund?',
  createdAt: '2026-09-19T12:00:00Z',
  messageId: null,
  phase: 'sending',
};

describe('outgoing turn', () => {
  it('shows customer text and the robot before an acknowledgement exists', () => {
    render(<OutgoingTurn message={message} />);
    expect(screen.getByText(message.content)).toBeInTheDocument();
    expect(screen.getByText('Sending…')).toBeInTheDocument();
    expect(screen.getByText('Working on your response…')).toBeInTheDocument();
  });

  it('stops the robot but retains the receipt when delivery is uncertain', () => {
    const view = render(<OutgoingTurn message={message} />);
    view.rerender(<OutgoingTurn message={{ ...message, phase: 'uncertain' }} />);
    expect(screen.getByText(message.content)).toBeInTheDocument();
    expect(screen.getByText(/Delivery unconfirmed/)).toBeInTheDocument();
    expect(screen.queryByText('Working on your response…')).not.toBeInTheDocument();
  });

  it('deduplicates only against the acknowledged message ID', () => {
    const saved = { ...message, messageId: 'server-message-1' };
    expect(shouldShowOutgoing(saved, [{ message_id: 'server-message-1' }])).toBe(false);
    expect(shouldShowOutgoing(saved, [{ message_id: 'an-older-identical-message' }])).toBe(true);
    expect(shouldShowOutgoing(message, [{ message_id: 'server-message-1' }])).toBe(true);
    expect(shouldShowOutgoing(null, [])).toBe(false);
  });

  it('keeps the history-loading indicator when the saved bubble is already visible', () => {
    render(<OutgoingTurn message={{ ...message, phase: 'syncing' }} showBubble={false} />);
    expect(screen.queryByText(message.content)).not.toBeInTheDocument();
    expect(screen.getByText('Loading the latest messages…')).toBeInTheDocument();
  });
});
