// apps/web/src/features/chat/response-rating.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { TransportContext } from '../../shared/api/transport-context';
import { responseFeedbackTargetKey } from './response-feedback-target';
import { ResponseRating } from './response-rating';

const auth = vi.hoisted(() => {
  const session = {
    phase: 'authenticated',
    error: null,
    user: {
      id: '00000000-0000-4000-8000-000000000001',
      email: 'customer@example.test',
      display_name: null,
      role: 'customer',
      status: 'active',
      created_at: '2026-09-15T10:00:00Z',
    },
  };

  return {
    session,
    current: session as unknown,
  };
});

vi.mock('../../shared/auth/session-context', () => ({
  useSession: () => auth.session,
  useSessionController: () => ({
    getSnapshot: () => auth.current,
  }),
}));

const conversationId = '00000000-0000-4000-8000-000000000002';
const responseMessageId = '00000000-0000-4000-8000-000000000003';
const aiRunId = '00000000-0000-4000-8000-000000000004';

const clients: QueryClient[] = [];

function receipt(created = true) {
  return Response.json(
    {
      feedback_id: '00000000-0000-4000-8000-000000000005',
      conversation_id: conversationId,
      customer_id: auth.session.user.id,
      response_message_id: responseMessageId,
      ai_run_id: aiRunId,
      rating: 4,
      status: 'pending',
      row_version: 1,
      created,
      reason_codes: [],
      helpful: null,
      comment: null,
    },
    { status: 201 },
  );
}

function setup(withTarget = true) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  clients.push(client);

  if (withTarget) {
    client.setQueryData(
      responseFeedbackTargetKey(auth.session.user.id, conversationId, responseMessageId),
      {
        conversationId,
        responseMessageId,
        aiRunId,
      },
    );
  }

  const fetchImpl = vi.fn<typeof fetch>();

  const transport = createTransport({
    apiOrigin: 'https://api.example.test',
    getAccessToken: () => 'test-only-token',
    fetchImpl,
  });

  function mount() {
    return render(
      <QueryClientProvider client={client}>
        <TransportContext.Provider value={transport}>
          <ResponseRating conversationId={conversationId} responseMessageId={responseMessageId} />
        </TransportContext.Provider>
      </QueryClientProvider>,
    );
  }

  return { client, fetchImpl, mount };
}

function chooseRating() {
  fireEvent.click(screen.getByRole('radio', { name: '4 — Good' }));
}

beforeEach(() => {
  auth.current = auth.session;
});

afterEach(() => {
  cleanup();
  for (const client of clients) client.clear();
  clients.length = 0;
});

describe('response rating', () => {
  it('hides controls when no confirmed association exists', () => {
    const { fetchImpl, mount } = setup(false);
    mount();

    expect(screen.queryByRole('form', { name: 'Rate this response' })).not.toBeInTheDocument();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('requires an explicit selection before sending', async () => {
    const { fetchImpl, mount } = setup();
    mount();

    for (const radio of screen.getAllByRole('radio')) {
      expect(radio).not.toBeChecked();
    }

    expect(screen.getByRole('button', { name: 'Submit rating' })).toBeDisabled();

    // Validation still protects programmatic form submission.
    fireEvent.submit(screen.getByRole('form', { name: 'Rate this response' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a rating from 1 to 5.');
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it.each([true, false])('confirms an acknowledged rating with created=%s', async (created) => {
    const { fetchImpl, mount } = setup();
    fetchImpl.mockResolvedValue(receipt(created));
    mount();

    chooseRating();
    fireEvent.click(screen.getByRole('button', { name: 'Submit rating' }));

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(
        created
          ? 'Your rating of 4 out of 5 was saved.'
          : 'Your rating of 4 out of 5 was already saved.',
      );
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Submit rating' })).toBeDisabled();
  });

  it('sends only once when two submits arrive before completion', async () => {
    const { fetchImpl, mount } = setup();

    let resolveResponse!: (response: Response) => void;
    fetchImpl.mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveResponse = resolve;
      }),
    );

    mount();
    chooseRating();

    const form = screen.getByRole('form', {
      name: 'Rate this response',
    });

    fireEvent.submit(form);
    fireEvent.submit(form);

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByRole('button', { name: 'Submit rating' })).toBeDisabled();

    await act(async () => {
      resolveResponse(receipt());
    });

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('was saved.');
    });
  });

  it('preserves an uncertain outcome across unmount and remount', async () => {
    const { fetchImpl, mount } = setup();
    fetchImpl.mockRejectedValue(new Error('Synthetic network failure'));

    const view = mount();
    chooseRating();
    fireEvent.click(screen.getByRole('button', { name: 'Submit rating' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'We could not confirm whether your rating was saved.',
    );

    view.unmount();
    mount();

    expect(screen.getByRole('alert')).toHaveTextContent(
      'We could not confirm whether your rating was saved.',
    );
    expect(screen.getByRole('button', { name: 'Submit rating' })).toBeDisabled();

    fireEvent.submit(screen.getByRole('form', { name: 'Rate this response' }));

    await act(async () => {
      await Promise.resolve();
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('does not replace conflicting feedback', async () => {
    const { fetchImpl, mount } = setup();
    fetchImpl.mockResolvedValue(
      Response.json(
        {
          error: {
            code: 'CONFLICT',
            message: 'Synthetic conflict',
          },
        },
        { status: 409 },
      ),
    );

    mount();
    chooseRating();
    fireEvent.click(screen.getByRole('button', { name: 'Submit rating' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'conflicts with the current feedback',
    );
    expect(screen.getByRole('button', { name: 'Submit rating' })).toBeDisabled();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('does not repopulate the cache after the session changes', async () => {
    const { client, fetchImpl, mount } = setup();

    let resolveResponse!: (response: Response) => void;
    fetchImpl.mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveResponse = resolve;
      }),
    );

    const view = mount();
    chooseRating();
    fireEvent.click(screen.getByRole('button', { name: 'Submit rating' }));

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    });

    auth.current = null;
    view.unmount();
    client.clear();

    await act(async () => {
      resolveResponse(receipt());
    });

    expect(client.getQueryCache().getAll()).toHaveLength(0);
  });

  it('reads the actual saved rating without submitting again', async () => {
    const { fetchImpl, mount } = setup();

    fetchImpl
      .mockRejectedValueOnce(new Error('Synthetic connection failure'))
      .mockResolvedValueOnce(
        Response.json({
          items: [
            {
              feedback_id: '00000000-0000-4000-8000-000000000005',
              conversation_id: conversationId,
              customer_id: auth.session.user.id,
              response_message_id: responseMessageId,
              rating: 2,
            },
          ],
          count: 1,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      );

    mount();
    chooseRating();

    fireEvent.click(screen.getByRole('button', { name: 'Submit rating' }));

    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Check saved rating',
      }),
    );

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(
        'Your rating of 2 out of 5 was already saved.',
      );
    });

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Submit rating' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Check saved rating' })).not.toBeInTheDocument();

    expect(fetchImpl.mock.calls.map((call) => call[1]?.method)).toEqual(['POST', 'GET']);

    expect(screen.getByRole('radio', { name: '2 — Fair' })).toBeChecked();
    expect(screen.getByRole('radio', { name: '4 — Good' })).not.toBeChecked();
    expect(screen.getByText('Fair', { exact: true })).toBeInTheDocument();
  });

  it('keeps submission paused when no saved rating is observed', async () => {
    const { fetchImpl, mount } = setup();

    fetchImpl
      .mockRejectedValueOnce(new Error('Synthetic connection failure'))
      .mockResolvedValueOnce(
        Response.json({
          items: [],
          count: 0,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      );

    mount();
    chooseRating();

    fireEvent.click(screen.getByRole('button', { name: 'Submit rating' }));

    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Check saved rating',
      }),
    );

    expect(
      await screen.findByText(/No saved rating was found in the records checked/),
    ).toBeInTheDocument();

    expect(screen.getByRole('button', { name: 'Submit rating' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Check saved rating' })).toBeEnabled();

    expect(fetchImpl.mock.calls.map((call) => call[1]?.method)).toEqual(['POST', 'GET']);
  });

  it('allows another read after a failed check without resending feedback', async () => {
    const { fetchImpl, mount } = setup();

    fetchImpl
      .mockRejectedValueOnce(new Error('Synthetic submission failure'))
      .mockRejectedValueOnce(new Error('Synthetic read failure'))
      .mockResolvedValueOnce(
        Response.json({
          items: [],
          count: 0,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      );

    mount();
    chooseRating();

    fireEvent.click(screen.getByRole('button', { name: 'Submit rating' }));

    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Check saved rating',
      }),
    );

    expect(await screen.findByText(/The saved rating could not be checked/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Check saved rating' }));

    expect(
      await screen.findByText(/No saved rating was found in the records checked/),
    ).toBeInTheDocument();

    expect(fetchImpl.mock.calls.map((call) => call[1]?.method)).toEqual(['POST', 'GET', 'GET']);
  });

  it('prevents overlapping checks', async () => {
    const { fetchImpl, mount } = setup();

    let resolveRead!: (response: Response) => void;

    fetchImpl.mockRejectedValueOnce(new Error('Synthetic submission failure')).mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        resolveRead = resolve;
      }),
    );

    mount();
    chooseRating();

    fireEvent.click(screen.getByRole('button', { name: 'Submit rating' }));

    const checkButton = await screen.findByRole('button', {
      name: 'Check saved rating',
    });

    fireEvent.click(checkButton);
    fireEvent.click(checkButton);

    await waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledTimes(2);
    });

    expect(checkButton).toBeDisabled();

    await act(async () => {
      resolveRead(
        Response.json({
          items: [],
          count: 0,
          limit: 100,
          offset: 0,
          has_more: false,
        }),
      );
    });

    expect(
      await screen.findByText(/No saved rating was found in the records checked/),
    ).toBeInTheDocument();

    expect(fetchImpl.mock.calls.map((call) => call[1]?.method)).toEqual(['POST', 'GET']);
  });

  it('previews stars without selecting or submitting', () => {
    const { fetchImpl, mount } = setup();
    mount();

    const good = screen.getByRole('radio', { name: '4 — Good' });
    const label = good.closest('label');

    if (!label) throw new Error('The rating label was not rendered.');

    fireEvent.pointerEnter(label, { pointerType: 'mouse' });

    expect(screen.getByText('Good', { exact: true })).toBeInTheDocument();

    for (const radio of screen.getAllByRole('radio')) {
      expect(radio).not.toBeChecked();
    }

    expect(screen.getByRole('button', { name: 'Submit rating' })).toBeDisabled();
    expect(fetchImpl).not.toHaveBeenCalled();

    const choices = label.parentElement;

    if (!choices) throw new Error('The rating choices were not rendered.');

    fireEvent.pointerLeave(choices);

    expect(screen.getByText('Choose a rating', { exact: true })).toBeInTheDocument();
  });

  it('restores the selection when hover ends', () => {
    const { fetchImpl, mount } = setup();
    mount();

    chooseRating();

    const excellent = screen.getByRole('radio', { name: '5 — Excellent' });
    const label = excellent.closest('label');

    if (!label) throw new Error('The rating label was not rendered.');

    fireEvent.pointerEnter(label, { pointerType: 'mouse' });

    expect(screen.getByText('Excellent', { exact: true })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: '4 — Good' })).toBeChecked();
    expect(excellent).not.toBeChecked();

    const choices = label.parentElement;

    if (!choices) throw new Error('The rating choices were not rendered.');

    fireEvent.pointerLeave(choices);

    expect(screen.getByText('Good', { exact: true })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Submit rating' })).toBeEnabled();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('provides a focus preview without committing feedback', () => {
    const { fetchImpl, mount } = setup();
    mount();

    const poor = screen.getByRole('radio', { name: '1 — Poor' });

    fireEvent.focus(poor);

    expect(screen.getByText('Poor', { exact: true })).toBeInTheDocument();
    expect(poor).not.toBeChecked();
    expect(fetchImpl).not.toHaveBeenCalled();

    fireEvent.blur(poor);

    expect(screen.getByText('Choose a rating', { exact: true })).toBeInTheDocument();
  });
});
