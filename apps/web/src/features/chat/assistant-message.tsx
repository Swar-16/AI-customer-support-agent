// apps/web/src/features/chat/assistant-message.tsx
import Markdown from 'react-markdown';
import type { Components } from 'react-markdown';

import { CopyButton } from './copy-button';

interface AssistantMessageProps {
  readonly content: string;
}

function safeLink(value: string): string {
  // Reject relative URLs, protocol-relative URLs, controls, and
  // backslash-based URL normalization surprises.
  const containsUnsafeCharacter = Array.from(value).some((character) => {
    const code = character.charCodeAt(0);
    return code <= 0x20 || code === 0x7f || character === '\\';
  });

  if (!/^https?:\/\//iu.test(value) || containsUnsafeCharacter) {
    return '';
  }

  try {
    const url = new URL(value);

    if (!['https:', 'http:'].includes(url.protocol) || url.username !== '' || url.password !== '') {
      return '';
    }

    return url.href;
  } catch {
    return '';
  }
}

const components: Components = {
  a({ href, children }) {
    const destination = href ? safeLink(href) : '';

    if (!destination) return <span>{children}</span>;

    return (
      <a href={destination} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">
        {children}
        <span className="chat-markdown__sr-only"> (opens in a new tab)</span>
      </a>
    );
  },

  // Preserve descriptive text without issuing an image request.
  img({ alt }) {
    return <span>{alt ? `[Image: ${alt}]` : '[Image omitted]'}</span>;
  },

  // Keep message headings below the conversation heading.
  h1({ children }) {
    return <h3>{children}</h3>;
  },
  h2({ children }) {
    return <h3>{children}</h3>;
  },
  h3({ children }) {
    return <h4>{children}</h4>;
  },
  h4({ children }) {
    return <h5>{children}</h5>;
  },
  h5({ children }) {
    return <h6>{children}</h6>;
  },
  h6({ children }) {
    return <h6>{children}</h6>;
  },

  pre({ children, node }) {
    const codeNode = node?.children.find(
      (child) => child.type === 'element' && child.tagName === 'code',
    );

    const text =
      codeNode?.type === 'element'
        ? codeNode.children.map((child) => (child.type === 'text' ? child.value : '')).join('')
        : null;

    return (
      <div className="chat-code-block">
        <pre tabIndex={0} aria-label="Code block">
          {children}
        </pre>
        {text !== null && <CopyButton text={text} label="Copy code" />}
      </div>
    );
  },
};

export function AssistantMessage({ content }: AssistantMessageProps) {
  return (
    <div className="chat-assistant-message">
      <div className="chat-history__content chat-markdown">
        <Markdown
          components={components}
          urlTransform={safeLink}
          allowedElements={[
            'p',
            'br',
            'strong',
            'em',
            'blockquote',
            'ul',
            'ol',
            'li',
            'hr',
            'h1',
            'h2',
            'h3',
            'h4',
            'h5',
            'h6',
            'pre',
            'code',
            'a',
            'img',
          ]}
        >
          {content}
        </Markdown>
      </div>

      <CopyButton text={content} label="Copy response" />
    </div>
  );
}
