// apps/web/src/features/chat/chat-page.test.tsx

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { TransportContext } from '../../shared/api/transport-context';
import ChatPage from './chat-page';
import { LogoutDialogProvider } from '../auth/logout-dialog';

const { session } = vi.hoisted(() => ({
  session: {
    phase: 'authenticated',
    error: null,
    user: {
      id: 'bf187e45-c833-444b-bcc5-39465b2be9fc',
      email: 'customer@example.test',
      display_name: null,
      role: 'customer',
      status: 'active',
      created_at: '2026-09-15T10:00:00Z',
    },
  },
}));

vi.mock('../../shared/auth/session-context', () => ({
  useSession: () => session,
  useSessionController: () => ({
    getSnapshot: () => session,
  }),
}));

const ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';

function conversation() {
  return {
    conversation_id: ID,
    customer_id: session.user.id,
    status: 'open',
    channel: 'web',
    title: 'Order question',
    created_at: '2026-09-15T10:00:00Z',
    updated_at: '2026-09-15T10:00:00Z',
    resolved_at: null,
    closed_at: null,
  };
}

function page<T>(items: T[], limit: number) {
  return {
    items,
    total: items.length,
    count: items.length,
    limit,
    offset: 0,
    has_more: false,
    next_offset: null,
  };
}

function setup(path = '/chat') {
  const fetchImpl = vi.fn<typeof fetch>();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const transport = createTransport({
    apiOrigin: 'https://api.example.test',
    getAccessToken: () => 'test-only-token',
    fetchImpl,
  });

  function mount() {
    const view = render(
      <QueryClientProvider client={queryClient}>
        <TransportContext.Provider value={transport}>
          <MemoryRouter initialEntries={[path]}>
            <LogoutDialogProvider>
              <Routes>
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/chat/:conversationId" element={<ChatPage />} />
              </Routes>
            </LogoutDialogProvider>
          </MemoryRouter>
        </TransportContext.Provider>
      </QueryClientProvider>,
    );

    return () => {
      view.unmount();
      queryClient.clear();
    };
  }

  return { fetchImpl, mount };
}

describe('Chat screen', () => {
  it('shows a real empty list without creating a conversation automatically', async () => {
    const { fetchImpl, mount } = setup();
    fetchImpl.mockResolvedValue(Response.json(page([], 25)));
    const cleanup = mount();

    expect(await screen.findByText('No conversations yet.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New conversation' })).toBeEnabled();

    expect(fetchImpl.mock.calls.some((call) => call[1]?.method === 'POST')).toBe(false);

    cleanup();
  });

  it('loads authorized history and renders HTML-looking content as text', async () => {
    const { fetchImpl, mount } = setup(`/chat/${ID}`);
    const content = '<script>doNotExecute()</script>';

    fetchImpl.mockImplementation(async (input) => {
      const url = new URL(String(input));

      if (url.pathname.endsWith('/messages')) {
        return Response.json(
          page(
            [
              {
                message_id: session.user.id,
                conversation_id: ID,
                role: 'assistant',
                content,
                sequence_number: 1,
                created_at: '2026-09-15T10:01:00Z',
              },
            ],
            50,
          ),
        );
      }

      if (url.pathname === `/v1/conversations/${ID}`) {
        return Response.json(conversation());
      }

      return Response.json(page([conversation()], 25));
    });

    const cleanup = mount();

    expect(await screen.findByText(content)).toBeInTheDocument();
    expect(document.querySelector('.chat-reading script')).toBeNull();
    expect(screen.getByText('Status: Open')).toBeInTheDocument();

    cleanup();
  });

  it('creates once and opens the returned conversation', async () => {
    const { fetchImpl, mount } = setup();

    fetchImpl.mockImplementation(async (input, init) => {
      const url = new URL(String(input));

      if (init?.method === 'POST') {
        return Response.json(conversation(), { status: 201 });
      }
      if (url.pathname.endsWith('/messages')) {
        return Response.json(page([], 50));
      }
      if (url.pathname === `/v1/conversations/${ID}`) {
        return Response.json(conversation());
      }

      return Response.json(page([], 25));
    });

    const cleanup = mount();
    await screen.findByText('No conversations yet.');

    const button = screen.getByRole('button', { name: 'New conversation' });
    fireEvent.click(button);
    fireEvent.click(button);

    expect(await screen.findByRole('heading', { name: 'Order question' })).toBeInTheDocument();

    expect(
      screen.queryByRole('heading', {
        name: /A little clarity, when you need it/,
      }),
    ).not.toBeInTheDocument();

    expect(
      screen.queryByRole('button', { name: 'Pause welcome animation' }),
    ).not.toBeInTheDocument();

    expect(screen.queryByRole('navigation', { name: 'Message pages' })).not.toBeInTheDocument();

    expect(fetchImpl.mock.calls.filter((call) => call[1]?.method === 'POST')).toHaveLength(1);

    cleanup();
  });

  it('blocks repeated creation after an uncertain response', async () => {
    const { fetchImpl, mount } = setup();

    fetchImpl.mockImplementation(async (_input, init) => {
      if (init?.method === 'POST') {
        throw new Error('Test network failure');
      }

      return Response.json(page([], 25));
    });

    const cleanup = mount();
    await screen.findByText('No conversations yet.');

    fireEvent.click(screen.getByRole('button', { name: 'New conversation' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Creation could not be confirmed.');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'New conversation' })).toBeDisabled();
    });

    expect(fetchImpl.mock.calls.filter((call) => call[1]?.method === 'POST')).toHaveLength(1);

    cleanup();
  });

  it('sends a message and renders the persisted assistant response', async () => {
    const { fetchImpl, mount } = setup(`/chat/${ID}`);

    let sent = false;
    const customerMessageId = '61315129-6698-44ad-b2c1-80dc5d1f002c';
    const assistantMessageId = '256c6cb2-f5da-4e50-a66f-539f78031887';
    const traceId = '77b7f548-b319-47a5-8a04-0cb67fef70d0';
    const answer = 'Your order is ready for collection.';

    fetchImpl.mockImplementation(async (input, init) => {
      const url = new URL(String(input));

      if (url.pathname.endsWith('/messages') && init?.method === 'POST') {
        sent = true;

        return Response.json({
          conversation_id: ID,
          customer_message_id: customerMessageId,
          ai_run_id: '2d125622-c20c-4f40-846c-4f6587b9e368',
          trace_id: traceId,
          pipeline_stage: 'guardrails_completed',
          intent: null,
          decision: null,
          assistant_message_id: assistantMessageId,
          escalation_id: null,
          response: answer,
          succeeded: true,
        });
      }

      if (url.pathname.endsWith('/messages')) {
        return Response.json(
          page(
            sent
              ? [
                  {
                    message_id: customerMessageId,
                    conversation_id: ID,
                    role: 'customer',
                    content: 'Where is my order?',
                    sequence_number: 1,
                    created_at: '2026-09-15T10:01:00Z',
                  },
                  {
                    message_id: assistantMessageId,
                    conversation_id: ID,
                    role: 'assistant',
                    content: answer,
                    sequence_number: 2,
                    created_at: '2026-09-15T10:01:01Z',
                  },
                ]
              : [],
            50,
          ),
        );
      }

      if (url.pathname === `/v1/conversations/${ID}`) {
        return Response.json(conversation());
      }

      return Response.json(page([conversation()], 25));
    });

    const cleanup = mount();

    try {
      await screen.findByText('No messages yet.');

      fireEvent.change(screen.getByRole('textbox', { name: 'Your message' }), {
        target: { value: 'Where is my order?' },
      });

      fireEvent.submit(screen.getByRole('form', { name: 'Send a message' }));

      expect(await screen.findByText(answer)).toBeInTheDocument();

      await waitFor(() => {
        expect(screen.getByRole('textbox', { name: 'Your message' })).toHaveValue('');
      });

      expect(fetchImpl.mock.calls.filter((call) => call[1]?.method === 'POST')).toHaveLength(1);
    } finally {
      cleanup();
    }
  });

  it('reconciles a failed send without resubmitting the message', async () => {
    const { fetchImpl, mount } = setup(`/chat/${ID}`);

    let attempted = false;

    fetchImpl.mockImplementation(async (input, init) => {
      const url = new URL(String(input));

      if (url.pathname.endsWith('/messages') && init?.method === 'POST') {
        attempted = true;

        return Response.json(
          {
            error: {
              code: 'AI_SERVICE_UNAVAILABLE',
              message: 'Service unavailable.',
            },
          },
          { status: 503 },
        );
      }

      if (url.pathname.endsWith('/messages')) {
        return Response.json(
          page(
            attempted
              ? [
                  {
                    message_id: '61315129-6698-44ad-b2c1-80dc5d1f002c',
                    conversation_id: ID,
                    role: 'customer',
                    content: 'Where is my order?',
                    sequence_number: 1,
                    created_at: '2026-09-15T10:01:00Z',
                  },
                ]
              : [],
            50,
          ),
        );
      }

      if (url.pathname === `/v1/conversations/${ID}`) {
        return Response.json(conversation());
      }

      return Response.json(page([conversation()], 25));
    });

    const cleanup = mount();

    try {
      await screen.findByText('No messages yet.');

      fireEvent.change(screen.getByRole('textbox', { name: 'Your message' }), {
        target: { value: 'Where is my order?' },
      });

      fireEvent.submit(screen.getByRole('form', { name: 'Send a message' }));

      expect(await screen.findByText(/The outcome could not be confirmed/)).toBeInTheDocument();

      expect(
        await screen.findByText('Where is my order?', {
          selector: '.chat-history__content',
        }),
      ).toBeInTheDocument();

      expect(screen.getByRole('textbox', { name: 'Your message' })).toBeDisabled();

      expect(fetchImpl.mock.calls.filter((call) => call[1]?.method === 'POST')).toHaveLength(1);
    } finally {
      cleanup();
    }
  });

  it('shows the welcome screen and hides unnecessary pagination', async () => {
    const { fetchImpl, mount } = setup();
    fetchImpl.mockResolvedValue(Response.json(page([], 25)));
    const cleanup = mount();

    try {
      await screen.findByText('No conversations yet.');

      expect(screen.getByRole('heading', { name: 'Customer Chat', level: 1 })).toBeInTheDocument();

      expect(
        screen.getByRole('heading', {
          name: /A little clarity, when you need it/,
        }),
      ).toBeInTheDocument();

      expect(
        screen.queryByRole('navigation', { name: 'Conversation pages' }),
      ).not.toBeInTheDocument();

      expect(screen.getByRole('button', { name: 'Refresh conversations' })).toHaveAttribute(
        'title',
        'Refresh conversations',
      );

      expect(screen.getByRole('button', { name: 'Sign out' })).toBeEnabled();
    } finally {
      cleanup();
    }
  });

  it('allows the welcome animation to be paused', async () => {
    const { fetchImpl, mount } = setup();
    fetchImpl.mockResolvedValue(Response.json(page([], 25)));
    const cleanup = mount();

    try {
      await screen.findByText('No conversations yet.');

      const pause = screen.getByRole('button', {
        name: 'Pause welcome animation',
      });

      expect(pause).toHaveAttribute('aria-pressed', 'false');
      fireEvent.click(pause);
      expect(pause).toHaveAttribute('aria-pressed', 'true');
      fireEvent.click(pause);
      expect(pause).toHaveAttribute('aria-pressed', 'false');
    } finally {
      cleanup();
    }
  });

  it('does not show the support action when no escalation is available', async () => {
    const { fetchImpl, mount } = setup(`/chat/${ID}`);

    fetchImpl.mockImplementation(async (input) => {
      const url = new URL(String(input));

      if (url.pathname.endsWith('/escalation-status')) {
        return Response.json({}, { status: 404 });
      }

      if (url.pathname.endsWith('/messages')) {
        return Response.json(page([], 50));
      }

      if (url.pathname === `/v1/conversations/${ID}`) {
        return Response.json(conversation());
      }

      return Response.json(page([conversation()], 25));
    });

    const cleanup = mount();

    try {
      await screen.findByText('No messages yet.');

      expect(screen.queryByRole('button', { name: 'Human support' })).not.toBeInTheDocument();
    } finally {
      cleanup();
    }
  });

  it('opens active support details and returns focus when dismissed', async () => {
    const { fetchImpl, mount } = setup(`/chat/${ID}`);

    fetchImpl.mockImplementation(async (input) => {
      const url = new URL(String(input));

      if (url.pathname.endsWith('/escalation-status')) {
        return Response.json({
          escalation_id: '00000000-0000-4000-8000-000000000099',
          conversation_id: ID,
          status: 'open',
          priority: 'normal',
          created_at: '2026-09-15T10:00:00Z',
          updated_at: '2026-09-15T10:00:00Z',
          resolved_at: null,
        });
      }

      if (url.pathname.endsWith('/messages')) {
        return Response.json(page([], 50));
      }

      if (url.pathname === `/v1/conversations/${ID}`) {
        return Response.json(conversation());
      }

      return Response.json(page([conversation()], 25));
    });

    const cleanup = mount();

    try {
      const trigger = await screen.findByRole('button', {
        name: 'Human support',
      });

      expect(trigger).toHaveAttribute('aria-expanded', 'false');
      fireEvent.click(trigger);

      const panel = screen.getByRole('complementary', {
        name: 'Support details',
      });

      expect(panel).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Support details' })).toHaveFocus();
      expect(trigger).toHaveAttribute('aria-expanded', 'true');

      fireEvent.keyDown(panel, { key: 'Escape' });

      expect(
        screen.queryByRole('complementary', { name: 'Support details' }),
      ).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    } finally {
      cleanup();
    }
  });

  it('opens the latest page and allows explicit navigation back to page zero', async () => {
    const { fetchImpl, mount } = setup(`/chat/${ID}`);
    const requestedOffsets: number[] = [];

    fetchImpl.mockImplementation(async (input) => {
      const url = new URL(String(input));

      if (url.pathname.endsWith('/escalation-status')) {
        return Response.json({}, { status: 404 });
      }

      if (url.pathname.endsWith('/messages')) {
        const offset = Number(url.searchParams.get('offset') ?? '0');
        requestedOffsets.push(offset);

        const count = Math.min(50, Math.max(0, 101 - offset));

        return Response.json({
          items: Array.from({ length: count }, (_, index) => {
            const sequence = offset + index + 1;

            return {
              message_id: `00000000-0000-4000-8000-${String(sequence).padStart(12, '0')}`,
              conversation_id: ID,
              role: 'customer',
              content: `Message ${sequence}`,
              sequence_number: sequence,
              created_at: '2026-09-15T10:00:00Z',
            };
          }),
          total: 101,
          count,
          limit: 50,
          offset,
          has_more: offset + count < 101,
          next_offset: offset + count < 101 ? offset + 50 : null,
        });
      }

      if (url.pathname === `/v1/conversations/${ID}`) {
        return Response.json(conversation());
      }

      return Response.json(page([conversation()], 25));
    });

    const cleanup = mount();

    try {
      expect(await screen.findByText('Message 101')).toBeInTheDocument();
      expect(requestedOffsets).toContain(100);

      expect(screen.queryByRole('button', { name: 'Later messages' })).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Earlier messages' }));

      expect(await screen.findByText('Message 51')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Earlier messages' }));

      expect(await screen.findByText('Message 1')).toBeInTheDocument();
      expect(screen.queryByText('Message 101')).not.toBeInTheDocument();

      expect(screen.queryByRole('button', { name: 'Earlier messages' })).not.toBeInTheDocument();

      expect(screen.getByRole('button', { name: 'Later messages' })).toBeEnabled();
    } finally {
      cleanup();
    }
  });

  it('returns to the welcome screen with Escape when the composer is empty', async () => {
    const { fetchImpl, mount } = setup(`/chat/${ID}`);

    fetchImpl.mockImplementation(async (input) => {
      const url = new URL(String(input));

      if (url.pathname.endsWith('/escalation-status')) {
        return Response.json({}, { status: 404 });
      }

      if (url.pathname.endsWith('/messages')) {
        return Response.json(page([], 50));
      }

      if (url.pathname === `/v1/conversations/${ID}`) {
        return Response.json(conversation());
      }

      return Response.json(page([conversation()], Number(url.searchParams.get('limit') ?? 1)));
    });

    const cleanup = mount();

    try {
      const composer = await screen.findByRole('textbox', {
        name: 'Your message',
      });

      await waitFor(() => expect(composer).toBeEnabled());
      fireEvent.keyDown(composer, { key: 'Escape' });

      expect(
        await screen.findByRole('heading', {
          name: /A little clarity, when you need it/,
        }),
      ).toBeInTheDocument();

      expect(fetchImpl.mock.calls.some((call) => call[1]?.method === 'POST')).toBe(false);
    } finally {
      cleanup();
    }
  });

  it('preserves an unsent draft when Escape is pressed', async () => {
    const { fetchImpl, mount } = setup(`/chat/${ID}`);

    fetchImpl.mockImplementation(async (input) => {
      const url = new URL(String(input));

      if (url.pathname.endsWith('/escalation-status')) {
        return Response.json({}, { status: 404 });
      }

      if (url.pathname.endsWith('/messages')) {
        return Response.json(page([], 50));
      }

      if (url.pathname === `/v1/conversations/${ID}`) {
        return Response.json(conversation());
      }

      return Response.json(page([conversation()], Number(url.searchParams.get('limit') ?? 1)));
    });

    const cleanup = mount();

    try {
      const composer = await screen.findByRole('textbox', {
        name: 'Your message',
      });

      await waitFor(() => expect(composer).toBeEnabled());

      fireEvent.change(composer, {
        target: { value: 'An unfinished question' },
      });
      fireEvent.keyDown(composer, { key: 'Escape' });

      expect(composer).toHaveValue('An unfinished question');
      expect(screen.getByRole('heading', { name: 'Order question' })).toBeInTheDocument();

      expect(
        screen.getByText(/Finish the current request or clear your unsent draft/),
      ).toBeInTheDocument();

      expect(fetchImpl.mock.calls.some((call) => call[1]?.method === 'POST')).toBe(false);
    } finally {
      cleanup();
    }
  });
});
