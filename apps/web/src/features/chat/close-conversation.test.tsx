// apps/web/src/features/chat/close-conversation.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CloseConversation } from './close-conversation';

function props() {
  return {
    closed: false,
    disabled: false,
    phase: 'idle' as const,
    notice: null,
    checking: false,
    canRetry: false,
    onClose: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
    onCheckStatus: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
  };
}

describe('CloseConversation', () => {
  it('requires explicit confirmation before closing', () => {
    const input = props();
    render(<CloseConversation {...input} />);

    fireEvent.click(screen.getByRole('button', { name: 'Close conversation' }));

    expect(input.onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Keep conversation open' })).toHaveFocus();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm close' }));

    expect(input.onClose).toHaveBeenCalledTimes(1);
  });

  it('cancels confirmation without submitting', () => {
    const input = props();
    render(<CloseConversation {...input} />);

    fireEvent.click(screen.getByRole('button', { name: 'Close conversation' }));

    fireEvent.click(screen.getByRole('button', { name: 'Keep conversation open' }));

    expect(input.onClose).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Confirm close' })).not.toBeInTheDocument();
  });

  it('does not offer closure while another operation disables it', () => {
    render(<CloseConversation {...props()} disabled />);

    expect(screen.getByRole('button', { name: 'Close conversation' })).toBeDisabled();
  });

  it('offers a status read after an uncertain result', () => {
    const input = props();

    render(
      <CloseConversation {...input} phase="uncertain" notice="Closure could not be confirmed." />,
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Check conversation status',
      }),
    );

    expect(input.onCheckStatus).toHaveBeenCalledTimes(1);
    expect(input.onClose).not.toHaveBeenCalled();

    expect(screen.queryByRole('button', { name: 'Confirm close again' })).not.toBeInTheDocument();
  });

  it('offers another explicit close only after reconciliation allows it', () => {
    const input = props();

    render(
      <CloseConversation
        {...input}
        phase="uncertain"
        canRetry
        notice="The conversation is currently not closed."
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Confirm close again' }));

    expect(input.onClose).toHaveBeenCalledTimes(1);
  });

  it('shows confirmed closure without an actionable close button', () => {
    render(
      <CloseConversation {...props()} closed phase="confirmed" notice="Conversation closed." />,
    );

    expect(screen.getByRole('status')).toHaveTextContent('Conversation closed.');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
