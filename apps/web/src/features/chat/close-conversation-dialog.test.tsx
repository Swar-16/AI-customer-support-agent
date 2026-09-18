// apps/web/src/features/chat/close-conversation-dialog.test.tsx

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

import { CloseConversation } from './close-conversation';

const prototype = HTMLDialogElement.prototype;
const originalShowModal = Object.getOwnPropertyDescriptor(prototype, 'showModal');
const originalClose = Object.getOwnPropertyDescriptor(prototype, 'close');

beforeAll(() => {
  Object.defineProperties(prototype, {
    showModal: {
      configurable: true,
      value(this: HTMLDialogElement) {
        this.setAttribute('open', '');
      },
    },
    close: {
      configurable: true,
      value(this: HTMLDialogElement) {
        this.removeAttribute('open');
      },
    },
  });
});

afterAll(() => {
  if (originalShowModal) {
    Object.defineProperty(prototype, 'showModal', originalShowModal);
  } else {
    Reflect.deleteProperty(prototype, 'showModal');
  }

  if (originalClose) {
    Object.defineProperty(prototype, 'close', originalClose);
  } else {
    Reflect.deleteProperty(prototype, 'close');
  }
});

afterEach(cleanup);

function props() {
  return {
    closed: false,
    disabled: false,
    phase: 'idle' as const,
    notice: null,
    checking: false,
    canRetry: false,
    onClose: vi.fn(async () => undefined),
    onCheckStatus: vi.fn(async () => undefined),
  };
}

describe('close conversation dialog', () => {
  it('opens without submitting and restores focus when cancelled', () => {
    const input = props();
    render(<CloseConversation {...input} />);

    const trigger = screen.getByRole('button', {
      name: 'Close conversation',
    });

    fireEvent.click(trigger);

    expect(
      screen.getByRole('dialog', {
        name: 'Close this conversation?',
      }),
    ).toBeInTheDocument();

    const cancel = screen.getByRole('button', {
      name: 'Keep conversation open',
    });

    expect(cancel).toHaveFocus();
    expect(input.onClose).not.toHaveBeenCalled();

    fireEvent.click(cancel);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(input.onClose).not.toHaveBeenCalled();
  });

  it('calls closure only after explicit confirmation', () => {
    const input = props();
    render(<CloseConversation {...input} />);

    fireEvent.click(screen.getByRole('button', { name: 'Close conversation' }));

    fireEvent.click(screen.getByRole('button', { name: 'Confirm close' }));

    expect(input.onClose).toHaveBeenCalledTimes(1);
  });

  it('keeps a pending request in the dialog, then announces confirmation', () => {
    const input = props();
    const view = render(<CloseConversation {...input} />);

    fireEvent.click(screen.getByRole('button', { name: 'Close conversation' }));

    view.rerender(<CloseConversation {...input} phase="pending" />);

    expect(screen.getByRole('button', { name: 'Keep conversation open' })).toBeDisabled();

    const dialog = screen.getByRole('dialog');
    fireEvent(dialog, new Event('cancel', { bubbles: false, cancelable: true }));

    expect(dialog).toHaveAttribute('open');

    view.rerender(
      <CloseConversation {...input} phase="confirmed" closed notice="Conversation closed." />,
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Conversation closed.');
    expect(screen.getByRole('status')).toHaveFocus();
  });

  it('shows recovery rather than success when closure is uncertain', () => {
    const input = props();
    const view = render(<CloseConversation {...input} />);

    fireEvent.click(screen.getByRole('button', { name: 'Close conversation' }));

    view.rerender(
      <CloseConversation {...input} phase="uncertain" notice="Closure could not be confirmed." />,
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveFocus();

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Check conversation status',
      }),
    );

    expect(input.onCheckStatus).toHaveBeenCalledTimes(1);
    expect(input.onClose).not.toHaveBeenCalled();
  });
});
