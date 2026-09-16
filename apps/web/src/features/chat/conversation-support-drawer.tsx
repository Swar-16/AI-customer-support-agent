// apps/web/src/features/chat/conversation-support-drawer.tsx

import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';

import { CustomerEscalationPanel } from './customer-escalation-panel';

interface ConversationSupportDrawerProps {
  readonly conversationId: string;
  readonly onClose: () => void;
}

export function ConversationSupportDrawer({
  conversationId,
  onClose,
}: ConversationSupportDrawerProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, []);

  return (
    <aside
      id="conversation-support-panel"
      className="conversation-support-drawer"
      aria-labelledby="conversation-support-title"
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <header className="conversation-support-drawer__header">
        <h2 id="conversation-support-title" ref={headingRef} tabIndex={-1}>
          Support details
        </h2>

        <button
          type="button"
          className="chat-icon-button"
          aria-label="Close support panel"
          title="Close support panel"
          onClick={onClose}
        >
          <X size={19} aria-hidden="true" />
        </button>
      </header>

      <CustomerEscalationPanel conversationId={conversationId} enabled />
    </aside>
  );
}
