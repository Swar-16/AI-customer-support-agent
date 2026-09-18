// apps/web/src/features/chat/copy-button.tsx
import { useEffect, useRef, useState } from 'react';
import { Check, Copy } from 'lucide-react';

interface CopyButtonProps {
  readonly text: string;
  readonly label: 'Copy response' | 'Copy code';
}

function CopyControl({ text, label }: CopyButtonProps) {
  const [state, setState] = useState<'idle' | 'pending' | 'copied' | 'failed'>('idle');

  const mountedRef = useRef(false);
  const inFlightRef = useRef(false);
  const resetTimerRef = useRef<number | null>(null);

  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;

      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
      }
    };
  }, []);

  async function copy() {
    if (inFlightRef.current) return;

    inFlightRef.current = true;

    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }

    setState('pending');

    try {
      if (!window.isSecureContext || typeof navigator.clipboard?.writeText !== 'function') {
        throw new Error('Clipboard unavailable.');
      }

      await navigator.clipboard.writeText(text);

      if (!mountedRef.current) return;

      setState('copied');

      resetTimerRef.current = window.setTimeout(() => {
        resetTimerRef.current = null;

        if (mountedRef.current) {
          setState('idle');
        }
      }, 2000);
    } catch {
      if (mountedRef.current) {
        setState('failed');
      }
    } finally {
      inFlightRef.current = false;
    }
  }

  return (
    <div className="chat-copy">
      <button
        type="button"
        className="chat-copy__button"
        data-state={state}
        aria-label={label}
        title={state === 'copied' ? 'Copied' : label}
        disabled={state === 'pending'}
        onClick={() => {
          void copy();
        }}
      >
        {state === 'copied' ? (
          <Check size={19} strokeWidth={2.4} aria-hidden="true" />
        ) : (
          <Copy size={18} aria-hidden="true" />
        )}
      </button>

      <span
        className={state === 'failed' ? 'chat-copy__error' : 'chat-markdown__sr-only'}
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {state === 'pending'
          ? 'Copying…'
          : state === 'copied'
            ? 'Copied.'
            : state === 'failed'
              ? 'Copy unavailable. Select the text and copy it manually.'
              : ''}
      </span>
    </div>
  );
}

export function CopyButton(props: CopyButtonProps) {
  // Reset state and cancel the timer when the supplied content changes.
  return <CopyControl key={props.text} {...props} />;
}
