// apps/web/src/features/chat/copy-button-feedback.test.tsx
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CopyButton } from './copy-button';

const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');

const writeText = vi.fn<(text: string) => Promise<void>>();

beforeEach(() => {
  writeText.mockReset();
  vi.stubGlobal('isSecureContext', true);

  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText },
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();

  if (originalClipboard) {
    Object.defineProperty(navigator, 'clipboard', originalClipboard);
  } else {
    Reflect.deleteProperty(navigator, 'clipboard');
  }
});

describe('copy icon feedback', () => {
  it('shows confirmation only after clipboard success, for two seconds', async () => {
    vi.useFakeTimers();

    let finish!: () => void;
    writeText.mockReturnValue(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );

    render(<CopyButton text="Synthetic response" label="Copy response" />);

    const button = screen.getByRole('button', {
      name: 'Copy response',
    });

    fireEvent.click(button);

    expect(button).toHaveAttribute('data-state', 'pending');
    expect(button).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Copying…');

    await act(async () => {
      finish();
    });

    expect(writeText).toHaveBeenCalledWith('Synthetic response');
    expect(button).toHaveAttribute('data-state', 'copied');
    expect(screen.getByRole('status')).toHaveTextContent('Copied.');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });

    expect(button).toHaveAttribute('data-state', 'copied');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(button).toHaveAttribute('data-state', 'idle');
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  it('shows a useful failure message without claiming success', async () => {
    writeText.mockRejectedValue(new Error('Synthetic clipboard failure'));

    render(<CopyButton text="Example code" label="Copy code" />);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy code' }));
    });

    expect(screen.getByRole('button', { name: 'Copy code' })).toHaveAttribute(
      'data-state',
      'failed',
    );

    expect(screen.getByRole('status')).toHaveTextContent(
      'Copy unavailable. Select the text and copy it manually.',
    );
    expect(screen.queryByText('Synthetic clipboard failure')).not.toBeInTheDocument();
  });

  it('resets confirmation when the content changes', async () => {
    writeText.mockResolvedValue(undefined);

    const view = render(<CopyButton text="First response" label="Copy response" />);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy response' }));
    });

    view.rerender(<CopyButton text="Second response" label="Copy response" />);

    expect(screen.getByRole('button', { name: 'Copy response' })).toHaveAttribute(
      'data-state',
      'idle',
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy response' }));
    });

    expect(writeText).toHaveBeenLastCalledWith('Second response');
  });
});
