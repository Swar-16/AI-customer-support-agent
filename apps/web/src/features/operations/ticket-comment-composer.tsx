// apps/web/src/features/operations/ticket-comment-composer.tsx
import { useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { CheckCircle2, LockKeyhole, Send, Users } from 'lucide-react';

import { SafeApiError } from '../../shared/api/safe-error';
import type { TicketCommentVisibility } from './ticket-contract';
import { useAddTicketComment } from './ticket-queries';

const MAX_COMMENT_LENGTH = 20_000;

function commentErrorMessage(error: unknown): string {
  return error instanceof SafeApiError ? error.message : 'The comment could not be added.';
}

export function TicketCommentComposer({ ticketId }: { readonly ticketId: string }) {
  const addComment = useAddTicketComment();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const submittingRef = useRef(false);

  const [visibility, setVisibility] = useState<TicketCommentVisibility>('customer');
  const [content, setContent] = useState('');
  const [confirmed, setConfirmed] = useState(false);

  const normalizedContent = content.trim();
  const disabled =
    normalizedContent.length === 0 ||
    normalizedContent.length > MAX_COMMENT_LENGTH ||
    addComment.isPending;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (disabled || submittingRef.current) return;

    submittingRef.current = true;
    setConfirmed(false);
    addComment.reset();

    try {
      await addComment.mutateAsync({
        ticketId,
        comment: {
          visibility,
          content: normalizedContent,
        },
      });

      setContent('');
      setConfirmed(true);

      if (textareaRef.current) {
        textareaRef.current.style.height = '';
        textareaRef.current.focus();
      }
    } catch {
      // Mutation error is rendered below the form.
    } finally {
      submittingRef.current = false;
    }
  }

  function handleKeyboard(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || !event.ctrlKey || event.nativeEvent.isComposing) {
      return;
    }

    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  return (
    <form
      className="ticket-comment-composer"
      onSubmit={(event) => {
        void submit(event);
      }}
    >
      <div className="ticket-comment-composer__heading">
        <strong>Add communication</strong>

        <div className="ticket-comment-visibility" aria-label="Comment visibility">
          <button
            type="button"
            aria-pressed={visibility === 'customer'}
            disabled={addComment.isPending}
            onClick={() => {
              setVisibility('customer');
              setConfirmed(false);
            }}
          >
            <Users size={15} aria-hidden="true" />
            Customer reply
          </button>

          <button
            type="button"
            aria-pressed={visibility === 'internal'}
            disabled={addComment.isPending}
            onClick={() => {
              setVisibility('internal');
              setConfirmed(false);
            }}
          >
            <LockKeyhole size={15} aria-hidden="true" />
            Internal note
          </button>
        </div>
      </div>

      <label>
        <span className="sr-only">Comment</span>

        <textarea
          ref={textareaRef}
          required
          rows={3}
          maxLength={MAX_COMMENT_LENGTH}
          value={content}
          placeholder={
            visibility === 'customer'
              ? 'Write an update the customer can see…'
              : 'Write a private note for support operators…'
          }
          onChange={(event) => {
            setContent(event.target.value);
            setConfirmed(false);
          }}
          onInput={(event) => {
            const textarea = event.currentTarget;
            textarea.style.height = 'auto';
            textarea.style.height = `${Math.min(textarea.scrollHeight, 220)}px`;
          }}
          onKeyDown={handleKeyboard}
        />
      </label>

      <div className="ticket-comment-composer__footer">
        <small>
          Ctrl+Enter to send · {content.length.toLocaleString()}/
          {MAX_COMMENT_LENGTH.toLocaleString()}
        </small>

        <button
          type="submit"
          className="ticket-comment-send"
          aria-label={visibility === 'customer' ? 'Send customer reply' : 'Add internal note'}
          title={visibility === 'customer' ? 'Send customer reply' : 'Add internal note'}
          aria-busy={addComment.isPending}
          disabled={disabled}
        >
          <Send size={17} aria-hidden="true" />
        </button>
      </div>

      {confirmed ? (
        <p className="ticket-comment-confirmation" role="status">
          <CheckCircle2 size={16} aria-hidden="true" />
          {visibility === 'customer' ? 'Customer reply added.' : 'Internal note added.'}
        </p>
      ) : null}

      {addComment.error ? (
        <p className="ticket-comment-error" role="alert">
          {commentErrorMessage(addComment.error)}
        </p>
      ) : null}
    </form>
  );
}
