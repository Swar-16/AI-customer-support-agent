import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TransportResult } from '../../shared/api/transport';
import type { SendMessageResult } from './chat-contract';
import { MessageComposer } from './message-composer';

function successfulResult(): TransportResult<SendMessageResult> {
  return {
    ok: true,
    traceId: '77b7f548-b319-47a5-8a04-0cb67fef70d0',
    data: {
      conversation_id: 'd44e99cb-8e10-4af8-9bb7-c4d293042943',
      customer_message_id: 'bf187e45-c833-444b-bcc5-39465b2be9fc',
      ai_run_id: '2d125622-c20c-4f40-846c-4f6587b9e368',
      trace_id: '77b7f548-b319-47a5-8a04-0cb67fef70d0',
      pipeline_stage: 'guardrails_completed',
      intent: null,
      decision: null,
      assistant_message_id: '256c6cb2-f5da-4e50-a66f-539f78031887',
      escalation_id: null,
      response: 'Here is the requested information.',
      succeeded: true,
    },
  };
}

function enterMessage(value = 'Where is my order?') {
  fireEvent.change(screen.getByRole('textbox', { name: 'Your message' }), {
    target: { value },
  });
}

function submitForm() {
  fireEvent.submit(screen.getByRole('form', { name: 'Send a message' }));
}

describe('MessageComposer', () => {
  it('rejects blank input without calling the send operation', async () => {
    const onSend = vi.fn<(message: string) => Promise<TransportResult<SendMessageResult>>>();

    render(<MessageComposer status="open" onSend={onSend} onReconcile={async () => true} />);

    enterMessage('   ');
    submitForm();

    expect(await screen.findByText('Enter a message.')).toBeInTheDocument();
    expect(onSend).not.toHaveBeenCalled();
  });

  it('prevents duplicate submissions before validation finishes', async () => {
    let resolveRequest: ((result: TransportResult<SendMessageResult>) => void) | undefined;

    const pending = new Promise<TransportResult<SendMessageResult>>((resolve) => {
      resolveRequest = resolve;
    });

    const onSend = vi.fn().mockReturnValue(pending);
    const onReconcile = vi.fn().mockResolvedValue(true);

    render(<MessageComposer status="open" onSend={onSend} onReconcile={onReconcile} />);

    enterMessage();

    act(() => {
      submitForm();
      submitForm();
    });

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByRole('textbox')).toBeDisabled();

    await act(async () => {
      if (!resolveRequest) throw new Error('Missing request resolver.');
      resolveRequest(successfulResult());
      await pending;
    });

    await waitFor(() => {
      expect(onReconcile).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('textbox')).toHaveValue('');
      expect(screen.getByRole('textbox')).toBeEnabled();
    });
  });

  it('requires explicit review after an uncertain result and never resends it', async () => {
    const onSend = vi.fn().mockResolvedValue({
      ok: false,
      error: SafeApiError.fromLocal('timeout'),
      retryAfterMs: null,
    });

    render(<MessageComposer status="open" onSend={onSend} onReconcile={async () => true} />);

    enterMessage();
    submitForm();

    expect(await screen.findByText(/The outcome could not be confirmed/)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole('checkbox')).toBeEnabled();
    });

    expect(screen.getByRole('textbox')).toHaveValue('Where is my order?');
    expect(screen.getByRole('textbox')).toBeDisabled();

    const newMessage = screen.getByRole('button', {
      name: 'Discard draft and write a new message',
    });

    expect(newMessage).toBeDisabled();

    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(newMessage);

    expect(screen.getByRole('textbox')).toHaveValue('');
    expect(screen.getByRole('textbox')).toBeEnabled();
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it('clears a confirmed draft even when history refresh fails', async () => {
    const onSend = vi.fn().mockResolvedValue(successfulResult());

    render(<MessageComposer status="open" onSend={onSend} onReconcile={async () => false} />);

    enterMessage();
    submitForm();

    expect(
      await screen.findByText(
        /Your message was received, but the latest history could not be loaded/,
      ),
    ).toBeInTheDocument();

    expect(screen.getByRole('textbox')).toHaveValue('');
    expect(screen.getByRole('textbox')).toBeDisabled();
    expect(screen.getByRole('checkbox')).toBeDisabled();
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it.each(['closed', 'resolved'] as const)('does not send in a %s conversation', async (status) => {
    const onSend = vi.fn();

    render(<MessageComposer status={status} onSend={onSend} onReconcile={async () => true} />);

    expect(screen.getByRole('textbox')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled();

    submitForm();

    expect(onSend).not.toHaveBeenCalled();
  });

  it('does not expose unexpected exception text', async () => {
    const onSend = vi
      .fn()
      .mockRejectedValue(new Error('Internal provider credentials and debug information'));

    render(<MessageComposer status="open" onSend={onSend} onReconcile={async () => true} />);

    enterMessage();
    submitForm();

    expect(await screen.findByText(/The outcome could not be confirmed/)).toBeInTheDocument();

    expect(screen.queryByText(/Internal provider credentials/)).not.toBeInTheDocument();
  });
});
