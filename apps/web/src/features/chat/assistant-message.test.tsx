// apps/web/src/features/chat/assistant-message.test.tsx
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AssistantMessage } from './assistant-message';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function clipboardMock() {
  const writeText = vi.fn<(text: string) => Promise<void>>();

  vi.stubGlobal('isSecureContext', true);
  vi.stubGlobal('navigator', {
    clipboard: { writeText },
  });

  return writeText;
}

describe('AssistantMessage', () => {
  it('renders Markdown and keeps headings below the conversation', () => {
    render(
      <AssistantMessage
        content={'# Policy\n\nPlease **keep your receipt**.\n\n- First\n- Second'}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Policy', level: 3 })).toBeInTheDocument();

    expect(screen.getByText('keep your receipt').tagName).toBe('STRONG');
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('renders raw HTML as text without creating executable elements', () => {
    const content = '<script>doNotExecute()</script>';
    const { container } = render(<AssistantMessage content={content} />);

    expect(screen.getByText(content)).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('[onclick]')).toBeNull();
  });

  it.each([
    'javascript:alert%281%29',
    'data:text/html,test',
    '//example.test/path',
    '/logout',
    'https://user:password@example.test/path',
  ])('does not make an unsafe or unsupported URL clickable: %s', (url) => {
    render(<AssistantMessage content={`[Open link](${url})`} />);

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText('Open link')).toBeInTheDocument();
  });

  it('allows an HTTPS link with isolation and no referrer', () => {
    render(<AssistantMessage content="[Policy](https://example.test/policy)" />);

    const link = screen.getByRole('link', { name: /Policy/ });

    expect(link).toHaveAttribute('href', 'https://example.test/policy');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAttribute('referrerpolicy', 'no-referrer');
  });

  it('does not render remote images', () => {
    const { container } = render(
      <AssistantMessage content="![Tracking image](https://example.test/pixel.png)" />,
    );

    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('[Image: Tracking image]')).toBeInTheDocument();
  });

  it('copies the original Markdown response', async () => {
    const writeText = clipboardMock();
    writeText.mockResolvedValue(undefined);

    const content = '**Keep your receipt.**';
    render(<AssistantMessage content={content} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy response' }));

    expect(await screen.findByText('Copied.')).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(content);
    expect(writeText).toHaveBeenCalledTimes(1);
  });

  it('copies code without the response or controls', async () => {
    const writeText = clipboardMock();
    writeText.mockResolvedValue(undefined);

    render(<AssistantMessage content={'Example:\n\n```js\nconst total = 2;\n```'} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy code' }));

    expect(await screen.findByText('Copied.')).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith('const total = 2;\n');
  });

  it('waits for clipboard confirmation and blocks duplicate clicks', async () => {
    const writeText = clipboardMock();

    let resolveWrite: (() => void) | undefined;
    const pending = new Promise<void>((resolve) => {
      resolveWrite = resolve;
    });

    writeText.mockReturnValue(pending);

    render(<AssistantMessage content="A response." />);

    const button = screen.getByRole('button', { name: 'Copy response' });

    fireEvent.click(button);
    fireEvent.click(button);

    expect(button).toBeDisabled();
    expect(screen.queryByText('Copied.')).not.toBeInTheDocument();
    expect(writeText).toHaveBeenCalledTimes(1);

    await act(async () => {
      if (!resolveWrite) throw new Error('Missing clipboard resolver.');
      resolveWrite();
      await pending;
    });

    expect(screen.getByText('Copied.')).toBeInTheDocument();
    expect(button).toBeEnabled();
  });

  it('reports clipboard failure without exposing the exception', async () => {
    const writeText = clipboardMock();
    writeText.mockRejectedValue(new Error('Private browser diagnostics'));

    render(<AssistantMessage content="A response." />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy response' }));

    expect(
      await screen.findByText('Copy unavailable. Select the text and copy it manually.'),
    ).toBeInTheDocument();

    expect(screen.queryByText('Copied.')).not.toBeInTheDocument();
    expect(screen.queryByText('Private browser diagnostics')).not.toBeInTheDocument();
  });

  it('handles a missing clipboard API', async () => {
    vi.stubGlobal('isSecureContext', true);
    vi.stubGlobal('navigator', {});

    render(<AssistantMessage content="A response." />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy response' }));

    expect(
      await screen.findByText('Copy unavailable. Select the text and copy it manually.'),
    ).toBeInTheDocument();
  });
});
