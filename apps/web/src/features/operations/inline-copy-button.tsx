// apps/web/src/features/operations/inline-copy-button.tsx
import { useState, type MouseEvent } from 'react';
import { Check, Copy } from 'lucide-react';

export interface InlineCopyButtonProps {
  readonly value: string;
  readonly label?: string;
  readonly className?: string;
  readonly size?: number;
}

export function InlineCopyButton({
  value,
  label = 'Copy to clipboard',
  className = '',
  size = 12,
}: InlineCopyButtonProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();

    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else if (typeof document !== 'undefined') {
        const textarea = document.createElement('textarea');
        textarea.value = value;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Gracefully handle clipboard write rejection
    }
  }

  const tooltip = copied ? 'Copied!' : label;
  const buttonClass = `operations-copy-button${copied ? ' is-copied' : ''}${
    className ? ` ${className}` : ''
  }`;

  return (
    <button
      type="button"
      className={buttonClass}
      onClick={handleCopy}
      aria-label={tooltip}
      title={tooltip}
    >
      {copied ? (
        <Check size={size} aria-hidden="true" />
      ) : (
        <Copy size={size} aria-hidden="true" />
      )}
    </button>
  );
}
