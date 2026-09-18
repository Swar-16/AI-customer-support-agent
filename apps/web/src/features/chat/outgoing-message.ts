// apps/web/src/features/chat/outgoing-message.ts
export interface OutgoingMessage {
  readonly localId: string;
  readonly content: string;
  readonly createdAt: string;
  readonly messageId: string | null;
  readonly phase: 'sending' | 'processing' | 'syncing' | 'saved' | 'uncertain' | 'rejected';
}

export function shouldShowOutgoing(
  outgoing: OutgoingMessage | null | undefined,
  history: readonly { readonly message_id: string }[],
): boolean {
  if (!outgoing) return false;
  return (
    outgoing.messageId === null ||
    !history.some((message) => message.message_id === outgoing.messageId)
  );
}
