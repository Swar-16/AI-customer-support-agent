// apps/web/src/features/operations/ticket-comment-composer.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { TransportContext } from '../../shared/api/transport-context';
import { TicketCommentComposer } from './ticket-comment-composer';

const auth = vi.hoisted(() => ({
  session: {
    phase: 'authenticated',
    error: null,
    user: {
      id: '2553fe11-ff42-4705-b9f8-b8540b882e96',
      email: 'agent@example.test',
      display_name: 'Support Agent',
      role: 'support_agent',
      status: 'active',
      created_at: '2026-09-19T05:00:00Z',
    },
  },
}));

vi.mock('../../shared/auth/session-context', () => ({
  useSession: () => auth.session,
}));

const TICKET_ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';

const COMMENT_ID = 'cc0d77af-2f31-470f-bd64-a374713b7e8c';

function commentReceipt(visibility: 'customer' | 'internal', content: string) {
  return {
    comment_id: COMMENT_ID,
    ticket_id: TICKET_ID,
    author_id: auth.session.user.id,
    author_role: 'support_agent',
    visibility,
    content,
    created_at: '2026-09-19T06:06:00Z',
  };
}

const clients: QueryClient[] = [];

function setup(fetchImplementation: typeof fetch) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });

  clients.push(queryClient);

  const fetchImpl = vi.fn(fetchImplementation);

  const transport = createTransport({
    apiOrigin: 'https://api.example.test',
    getAccessToken: () => 'test-only-token',
    fetchImpl,
  });

  render(
    <QueryClientProvider client={queryClient}>
      <TransportContext.Provider value={transport}>
        <TicketCommentComposer ticketId={TICKET_ID} />
      </TransportContext.Provider>
    </QueryClientProvider>,
  );

  return { fetchImpl };
}

afterEach(() => {
  cleanup();

  for (const client of clients) {
    client.clear();
  }

  clients.length = 0;
});

describe('ticket comment composer', () => {
  it('sends a customer-visible reply with Ctrl+Enter', async () => {
    const content = 'We are reviewing your payment.';

    const { fetchImpl } = setup(async () =>
      Response.json(commentReceipt('customer', content), {
        status: 201,
      }),
    );

    const textarea = screen.getByLabelText('Comment');

    fireEvent.change(textarea, {
      target: {
        value: content,
      },
    });

    fireEvent.keyDown(textarea, {
      key: 'Enter',
      code: 'Enter',
      ctrlKey: true,
    });

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    expect(JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body))).toEqual({
      visibility: 'customer',
      content,
    });

    expect(await screen.findByText('Customer reply added.')).toBeInTheDocument();

    expect(textarea).toHaveValue('');
  });

  it('sends an internal note only after selecting it', async () => {
    const content = 'Check the payment processor logs.';

    const { fetchImpl } = setup(async () =>
      Response.json(commentReceipt('internal', content), {
        status: 201,
      }),
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Internal note',
      }),
    );

    fireEvent.change(screen.getByLabelText('Comment'), {
      target: {
        value: content,
      },
    });

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Add internal note',
      }),
    );

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    expect(JSON.parse(String(fetchImpl.mock.calls[0]?.[1]?.body))).toEqual({
      visibility: 'internal',
      content,
    });

    expect(await screen.findByText('Internal note added.')).toBeInTheDocument();
  });

  it('keeps submission disabled for a blank comment', () => {
    const { fetchImpl } = setup(async () =>
      Response.json(commentReceipt('customer', 'Unused'), {
        status: 201,
      }),
    );

    const submit = screen.getByRole('button', {
      name: 'Send customer reply',
    });

    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Comment'), {
      target: {
        value: '   ',
      },
    });

    expect(submit).toBeDisabled();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('prevents duplicate submissions while pending', async () => {
    let resolveRequest: ((response: Response) => void) | undefined;

    const pendingResponse = new Promise<Response>((resolve) => {
      resolveRequest = resolve;
    });

    const { fetchImpl } = setup(async () => pendingResponse);

    fireEvent.change(screen.getByLabelText('Comment'), {
      target: {
        value: 'One message only.',
      },
    });

    const submit = screen.getByRole('button', {
      name: 'Send customer reply',
    });

    fireEvent.click(submit);
    fireEvent.click(submit);

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      resolveRequest?.(
        Response.json(commentReceipt('customer', 'One message only.'), {
          status: 201,
        }),
      );

      await pendingResponse;
    });

    expect(await screen.findByText('Customer reply added.')).toBeInTheDocument();
  });
});
