import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { MessageScrollBoundary } from './message-scroll-boundary';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function fixture(count: number, pageKey = 'conversation:0') {
  return (
    <main className="chat-reading" data-testid="reading-pane">
      <MessageScrollBoundary pageKey={pageKey} ready lastSequence={count === 0 ? null : count}>
        <ol>
          {Array.from({ length: count }, (_, index) => (
            <li key={index} data-chat-message="" tabIndex={-1}>
              Message {index + 1}
            </li>
          ))}
        </ol>
      </MessageScrollBoundary>
    </main>
  );
}

function setGeometry(pane: HTMLElement) {
  Object.defineProperty(pane, 'clientHeight', {
    configurable: true,
    get: () => 600,
  });

  Object.defineProperty(pane, 'scrollHeight', {
    configurable: true,
    get: () => 400 + pane.querySelectorAll('[data-chat-message]').length * 400,
  });
}

describe('MessageScrollBoundary', () => {
  it('follows new messages when previously near the bottom', () => {
    const view = render(fixture(1));
    const pane = screen.getByTestId('reading-pane');
    setGeometry(pane);

    // One message: height 800, viewport 600, bottom at 200.
    pane.scrollTop = 200;

    view.rerender(fixture(2));

    // The browser clamps this assignment to its maximum scroll position.
    // JSDOM retains the assigned value.
    expect(pane.scrollTop).toBe(1200);
    expect(screen.queryByRole('button', { name: 'New messages' })).not.toBeInTheDocument();
  });

  it('preserves position and announces new messages when reading above', () => {
    const view = render(fixture(1));
    const pane = screen.getByTestId('reading-pane');
    setGeometry(pane);
    pane.scrollTop = 0;

    view.rerender(fixture(2));

    expect(pane.scrollTop).toBe(0);
    expect(screen.getByRole('button', { name: 'New messages' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('New messages are available below.');
  });

  it('does not treat pagination as arriving messages', () => {
    const view = render(fixture(1));
    const pane = screen.getByTestId('reading-pane');
    setGeometry(pane);
    pane.scrollTop = 200;

    view.rerender(fixture(2, 'conversation:50'));

    expect(pane.scrollTop).toBe(200);
    expect(screen.queryByRole('button', { name: 'New messages' })).not.toBeInTheDocument();
  });

  it('clears the notice after the reader reaches the bottom', () => {
    const view = render(fixture(1));
    const pane = screen.getByTestId('reading-pane');
    setGeometry(pane);
    pane.scrollTop = 0;

    view.rerender(fixture(2));

    expect(screen.getByRole('button', { name: 'New messages' })).toBeInTheDocument();

    pane.scrollTop = 600;
    fireEvent.scroll(pane);

    expect(screen.queryByRole('button', { name: 'New messages' })).not.toBeInTheDocument();
  });

  it.each([
    [true, 'auto'],
    [false, 'smooth'],
  ] as const)('uses reduced motion=%s for an explicit jump', (reducedMotion, behavior) => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: reducedMotion }));

    const view = render(fixture(1));
    const pane = screen.getByTestId('reading-pane');
    setGeometry(pane);
    pane.scrollTop = 0;

    const scrollTo = vi.fn();
    Object.defineProperty(pane, 'scrollTo', {
      configurable: true,
      value: scrollTo,
    });

    view.rerender(fixture(2));

    fireEvent.click(screen.getByRole('button', { name: 'New messages' }));

    expect(screen.getByText('Message 2')).toHaveFocus();
    expect(scrollTo).toHaveBeenCalledWith({
      top: expect.any(Number),
      behavior,
    });
    expect(screen.queryByRole('button', { name: 'New messages' })).not.toBeInTheDocument();
  });

  it('does not scroll for an ordinary rerender', () => {
    const view = render(fixture(1));
    const pane = screen.getByTestId('reading-pane');
    setGeometry(pane);
    pane.scrollTop = 100;

    view.rerender(fixture(1));

    expect(pane.scrollTop).toBe(100);
    expect(screen.queryByRole('button', { name: 'New messages' })).not.toBeInTheDocument();
  });
});
