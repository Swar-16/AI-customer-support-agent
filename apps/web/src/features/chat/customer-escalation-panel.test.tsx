// apps/web/src/features/chat/customer-escalation-panel.test.tsx
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { createTransport } from '../../shared/api/transport';
import { TransportContext } from '../../shared/api/transport-context';
import { CustomerEscalationPanel } from './customer-escalation-panel';

vi.mock('../../shared/auth/session-context', () => ({
  useSession: () => ({
    phase: 'authenticated',
    user: {
      id: 'bf187e45-c833-444b-bcc5-39465b2be9fc',
      role: 'customer',
      status: 'active',
    },
  }),
}));

const ID = 'd44e99cb-8e10-4af8-9bb7-c4d293042943';

function escalation() {
  return {
    escalation_id: '458890db-2435-4267-895d-9aa795dcd8cb',
    conversation_id: ID,
    status: 'in_review',
    priority: 'normal',
    created_at: '2026-09-15T10:00:00Z',
    updated_at: '2026-09-15T10:05:00Z',
    resolved_at: null,
  };
}

function setup(enabled = true) {
  const fetchImpl = vi.fn<typeof fetch>();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  const transport = createTransport({
    apiOrigin: 'https://api.example.test',
    getAccessToken: () => 'test-only-token',
    fetchImpl,
  });

  function Wrapper({ children }: { readonly children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <TransportContext.Provider value={transport}>{children}</TransportContext.Provider>
      </QueryClientProvider>
    );
  }

  function mount() {
    const view = render(<CustomerEscalationPanel conversationId={ID} enabled={enabled} />, {
      wrapper: Wrapper,
    });

    return () => {
      view.unmount();
      queryClient.clear();
    };
  }

  return { fetchImpl, mount };
}

describe('CustomerEscalationPanel', () => {
  it('renders customer-safe status without internal details', async () => {
    const test = setup();

    test.fetchImpl.mockResolvedValue(
      Response.json({
        ...escalation(),
        handoff_summary: 'Internal test handoff',
      }),
    );

    const dispose = test.mount();

    try {
      expect(await screen.findByText('In review')).toBeInTheDocument();
      expect(screen.getByText('Normal')).toBeInTheDocument();
      expect(screen.getByText('Latest escalation')).toBeInTheDocument();

      expect(screen.queryByText('Internal test handoff')).not.toBeInTheDocument();
    } finally {
      dispose();
    }
  });

  it('renders 404 as unavailable status rather than a confirmed empty escalation', async () => {
    const test = setup();

    test.fetchImpl.mockResolvedValue(
      Response.json(
        { error: { code: 'TEST_NOT_FOUND', message: 'Unavailable.' } },
        { status: 404 },
      ),
    );

    const dispose = test.mount();

    try {
      expect(
        await screen.findByText('No support status is available for this conversation.'),
      ).toBeInTheDocument();

      expect(screen.queryByText('Latest escalation')).not.toBeInTheDocument();
      expect(test.fetchImpl).toHaveBeenCalledTimes(1);
    } finally {
      dispose();
    }
  });

  it('labels retained data as last known after a failed refresh', async () => {
    const test = setup();

    test.fetchImpl
      .mockResolvedValueOnce(Response.json(escalation()))
      .mockRejectedValueOnce(new Error('Simulated network failure'));

    const dispose = test.mount();

    try {
      await screen.findByText('In review');

      fireEvent.click(screen.getByRole('button', { name: 'Refresh support status' }));

      expect(await screen.findByText('Last known escalation')).toBeInTheDocument();

      expect(screen.getByText('In review')).toBeInTheDocument();
      expect(screen.getByRole('alert')).toHaveTextContent('could not be refreshed');

      expect(test.fetchImpl).toHaveBeenCalledTimes(2);
    } finally {
      dispose();
    }
  });

  it('hides previous data when a refresh returns forbidden', async () => {
    const test = setup();

    test.fetchImpl
      .mockResolvedValueOnce(Response.json(escalation()))
      .mockResolvedValueOnce(
        Response.json(
          { error: { code: 'TEST_FORBIDDEN', message: 'Unavailable.' } },
          { status: 403 },
        ),
      );

    const dispose = test.mount();

    try {
      await screen.findByText('In review');

      fireEvent.click(screen.getByRole('button', { name: 'Refresh support status' }));

      await waitFor(() => {
        expect(screen.queryByText('In review')).not.toBeInTheDocument();
      });

      expect(screen.getByRole('alert')).toHaveTextContent('Your access may have changed');
    } finally {
      dispose();
    }
  });

  it('does not fetch while the conversation is unverified', () => {
    const test = setup(false);
    const dispose = test.mount();

    try {
      expect(test.fetchImpl).not.toHaveBeenCalled();
      expect(screen.getByRole('button', { name: 'Refresh support status' })).toBeDisabled();
    } finally {
      dispose();
    }
  });
});
