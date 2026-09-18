// apps/web/src/features/chat/outgoing-turn.tsx
import { useLayoutEffect, useRef } from 'react';
import type { OutgoingMessage } from './outgoing-message';
import { AgentWorking } from './agent-working';
import './outgoing-turn.css';

const deliveryLabels: Record<OutgoingMessage['phase'], string> = {
  sending: 'Sending…',
  processing: 'Conversation created · response pending',
  syncing: 'Message saved',
  saved: 'Message saved',
  uncertain: 'Delivery unconfirmed · review history before sending again',
  rejected: 'Request not accepted · review the message field',
};

export function OutgoingTurn({
  message,
  showBubble = true,
}: {
  readonly message: OutgoingMessage;
  readonly showBubble?: boolean;
}) {
  const hostRef = useRef<HTMLDivElement>(null);

  // Reveal an explicitly submitted turn once. Subsequent updates leave the
  // existing history scroll boundary in charge of following saved messages.
  useLayoutEffect(() => {
    const host = hostRef.current;
    const pane = host?.closest<HTMLElement>('[data-chat-scroll]');
    if (!host || !pane) return;
    const targetBottom = host.getBoundingClientRect().bottom;
    const paneBottom = pane.getBoundingClientRect().bottom;
    pane.scrollTop = Math.max(0, pane.scrollTop + targetBottom - paneBottom + 24);
  }, [message.localId]);

  const working = message.phase === 'sending' || message.phase === 'processing';

  return (
    <div ref={hostRef} className="outgoing-turn" data-delivery={message.phase}>
      {showBubble && (
        <article
          className="chat-history__message outgoing-turn__bubble"
          data-speaker="customer"
          aria-label="Your submitted message"
        >
          <header>
            <strong>You</strong>
            <time dateTime={message.createdAt}>
              {new Date(message.createdAt).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
              })}
            </time>
          </header>
          <p className="chat-history__content">{message.content}</p>
          <p className="outgoing-turn__delivery" role="status">
            {deliveryLabels[message.phase]}
          </p>
        </article>
      )}
      {working && <AgentWorking />}
      {message.phase === 'syncing' && <AgentWorking label="Loading the latest messages…" />}
    </div>
  );
}
