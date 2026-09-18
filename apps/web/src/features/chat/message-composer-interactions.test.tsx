// apps/web/src/features/chat/message-composer-interactions.test.tsx

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import type { SendMessageResult } from './chat-contract';
import { MessageComposer } from './message-composer';

afterEach(cleanup);

function success(): TransportResult<SendMessageResult> {
  return {
    ok: true,
    traceId: null,
    data: {
      conversation_id: '00000000-0000-4000-8000-000000000001',
      customer_message_id: '00000000-0000-4000-8000-000000000002',
      ai_run_id: '00000000-0000-4000-8000-000000000003',
      trace_id: '00000000-0000-4000-8000-000000000004',
      pipeline_stage: 'guardrails_completed',
      intent: null,
      decision: null,
      assistant_message_id: '00000000-0000-4000-8000-000000000005',
      escalation_id: null,
      response: 'Synthetic response.',
      succeeded: true,
    },
  };
}

describe('composer interactions', () => {
  it('clears immediately while sending and restores focus after success', async () => {
    let finish!: (result: TransportResult<SendMessageResult>) => void;

    const onSend = vi.fn(
      () =>
        new Promise<TransportResult<SendMessageResult>>((resolve) => {
          finish = resolve;
        }),
    );

    render(<MessageComposer status="open" onSend={onSend} onReconcile={async () => true} />);

    const input = screen.getByRole('textbox', { name: 'Your message' });
    input.focus();

    fireEvent.change(input, {
      target: { value: 'Where is my order?' },
    });

    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true });

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledTimes(1);
      expect(input).toHaveValue('');
    });

    expect(screen.getByText('Updating your conversation…')).toBeInTheDocument();

    fireEvent.submit(screen.getByRole('form', { name: 'Send a message' }));
    expect(onSend).toHaveBeenCalledTimes(1);

    await act(async () => {
      finish(success());
    });

    await waitFor(() => {
      expect(input).toBeEnabled();
      expect(input).toHaveFocus();
    });

    expect(
      screen.queryByRole('button', { name: 'Return to message field' }),
    ).not.toBeInTheDocument();
  });

  it('restores an uncertain draft without automatically resending it', async () => {
    const onSend = vi.fn<(message: string) => Promise<TransportResult<SendMessageResult>>>();

    onSend.mockResolvedValue({
      ok: false,
      error: SafeApiError.fromLocal('network'),
      retryAfterMs: null,
    });

    render(<MessageComposer status="open" onSend={onSend} onReconcile={async () => true} />);

    const input = screen.getByRole('textbox', { name: 'Your message' });

    fireEvent.change(input, {
      target: { value: 'Where is my order?' },
    });
    fireEvent.submit(screen.getByRole('form', { name: 'Send a message' }));

    await waitFor(() => {
      expect(input).toHaveValue('Where is my order?');
      expect(input).toBeDisabled();
    });

    expect(await screen.findByText(/The outcome could not be confirmed/)).toBeInTheDocument();
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it('does not submit on plain Enter or during IME composition', () => {
    const onSend = vi.fn(async () => success());

    render(<MessageComposer status="open" onSend={onSend} onReconcile={async () => true} />);

    const input = screen.getByRole('textbox', { name: 'Your message' });

    fireEvent.change(input, { target: { value: 'A question' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    fireEvent.keyDown(input, {
      key: 'Enter',
      ctrlKey: true,
      isComposing: true,
    });

    expect(onSend).not.toHaveBeenCalled();
  });
});
