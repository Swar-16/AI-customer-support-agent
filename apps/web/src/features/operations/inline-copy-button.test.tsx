// apps/web/src/features/operations/inline-copy-button.test.tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { InlineCopyButton } from './inline-copy-button';

describe('InlineCopyButton', () => {
  const writeTextMock = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    vi.clearAllMocks();
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });
  });

  it('renders with label and copies text on click', async () => {
    const parentClickMock = vi.fn();

    render(
      <div onClick={parentClickMock}>
        <InlineCopyButton value="01a20ee9-483c-70b1-94f6-1f7f7378cdb3" label="Copy conversation ID" />
      </div>,
    );

    const button = screen.getByRole('button', { name: 'Copy conversation ID' });
    expect(button).toBeInTheDocument();

    fireEvent.click(button);

    expect(writeTextMock).toHaveBeenCalledWith('01a20ee9-483c-70b1-94f6-1f7f7378cdb3');
    // Ensure event propagation was stopped
    expect(parentClickMock).not.toHaveBeenCalled();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Copied!' })).toBeInTheDocument();
    });
  });
});
