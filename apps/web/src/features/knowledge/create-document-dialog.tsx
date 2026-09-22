// apps/web/src/features/knowledge/create-document-dialog.tsx

import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { FilePlus2, Info, LoaderCircle, X } from 'lucide-react';
import { useForm, type SubmitHandler } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import type { z } from 'zod';

import {
  createKnowledgeDocumentInputSchema,
  type KnowledgeContentType,
  type KnowledgeVisibility,
} from './knowledge-contract';
import { formatContentType, formatKnowledgeVisibility } from './knowledge-formatters';
import { useCreateKnowledgeDocument } from './knowledge-queries';

import './knowledge-dialog.css';

interface CreateDocumentDialogProps {
  readonly open: boolean;
  readonly onClose: () => void;

  readonly onCreated: (documentId: string) => void;
}

type CreateDocumentFormInput = z.input<typeof createKnowledgeDocumentInputSchema>;

type CreateDocumentFormOutput = z.output<typeof createKnowledgeDocumentInputSchema>;

const contentTypes = [
  'policy',
  'faq',
  'procedure',
  'guide',
  'reference',
  'other',
] satisfies readonly KnowledgeContentType[];

const visibilityOptions = ['customer', 'internal', 'both'] satisfies readonly KnowledgeVisibility[];

const defaultValues: CreateDocumentFormInput = {
  title: '',
  description: '',
  content_type: 'faq',
  visibility: 'customer',
};

export function CreateDocumentDialog({ open, onClose, onCreated }: CreateDocumentDialogProps) {
  const titleId = useId();
  const descriptionId = useId();

  const dialogRef = useRef<HTMLDialogElement>(null);

  const triggerRef = useRef<HTMLElement | null>(null);

  const previouslyOpenRef = useRef(false);

  const createDocument = useCreateKnowledgeDocument();

  const {
    register,
    handleSubmit,
    reset,
    setFocus,
    formState: { errors, isValid },
  } = useForm<CreateDocumentFormInput, unknown, CreateDocumentFormOutput>({
    resolver: zodResolver(createKnowledgeDocumentInputSchema),

    defaultValues,

    mode: 'onChange',
  });

  const pending = createDocument.isPending;

  const unconfirmed =
    createDocument.isError &&
    (createDocument.error.kind === 'network' || createDocument.error.kind === 'timeout');

  useEffect(() => {
    const dialog = dialogRef.current;

    if (dialog === null) {
      return;
    }

    if (open && !previouslyOpenRef.current) {
      triggerRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;

      if (!dialog.open) {
        dialog.showModal();
      }

      window.requestAnimationFrame(() => {
        setFocus('title');
      });
    }

    if (!open && previouslyOpenRef.current) {
      if (dialog.open) {
        dialog.close();
      }

      if (triggerRef.current?.isConnected) {
        triggerRef.current.focus({
          preventScroll: true,
        });
      }

      triggerRef.current = null;
    }

    previouslyOpenRef.current = open;
  }, [open, setFocus]);

  useEffect(
    () => () => {
      const dialog = dialogRef.current;

      if (dialog?.open) {
        dialog.close();
      }
    },
    [],
  );

  function requestClose() {
    if (pending) {
      return;
    }

    reset(defaultValues);
    createDocument.reset();
    onClose();
  }

  const submit: SubmitHandler<CreateDocumentFormOutput> = (values) => {
    if (pending || unconfirmed) {
      return;
    }

    const normalizedDescription = values.description?.trim() || null;

    createDocument.mutate(
      {
        title: values.title,
        description: normalizedDescription,
        content_type: values.content_type,
        visibility: values.visibility,
      },
      {
        onSuccess: (response) => {
          reset(defaultValues);
          createDocument.reset();

          onCreated(response.document_id);
        },
      },
    );
  };

  if (!open) {
    return null;
  }

  return createPortal(
    <dialog
      ref={dialogRef}
      className="knowledge-confirmation-dialog knowledge-create-document-dialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      aria-modal="true"
      aria-busy={pending}
      onCancel={(event) => {
        event.preventDefault();
        requestClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          requestClose();
        }
      }}
    >
      <section className="knowledge-confirmation-dialog__card">
        <div className="knowledge-confirmation-dialog__topline">
          <span className="knowledge-confirmation-dialog__icon" aria-hidden="true">
            <FilePlus2 size={25} />
          </span>

          <button
            type="button"
            className="knowledge-confirmation-dialog__dismiss"
            aria-label="Close create document dialog"
            disabled={pending}
            onClick={requestClose}
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        <div className="knowledge-confirmation-dialog__copy">
          <h2 id={titleId} tabIndex={-1}>
            Create a knowledge document
          </h2>

          <p id={descriptionId}>
            Create the stable document identity first. You can add its first immutable source
            version afterwards.
          </p>
        </div>

        <form
          className="knowledge-create-document-dialog__form"
          noValidate
          onSubmit={(event) => {
            void handleSubmit(submit)(event);
          }}
        >
          <div className="knowledge-dialog-fields">
            <label className="knowledge-dialog-field" data-invalid={errors.title !== undefined}>
              <span className="knowledge-dialog-field__label">Title</span>

              <input
                type="text"
                autoComplete="off"
                maxLength={300}
                disabled={pending}
                aria-invalid={errors.title !== undefined}
                aria-describedby={
                  errors.title === undefined ? undefined : 'knowledge-create-title-error'
                }
                {...register('title')}
              />

              {errors.title !== undefined && (
                <span
                  id="knowledge-create-title-error"
                  className="knowledge-dialog-field__error"
                  role="alert"
                >
                  {errors.title.message}
                </span>
              )}
            </label>

            <label
              className="knowledge-dialog-field"
              data-invalid={errors.description !== undefined}
            >
              <span className="knowledge-dialog-field__label">
                Description
                <small>Optional</small>
              </span>

              <textarea
                maxLength={2_000}
                disabled={pending}
                aria-invalid={errors.description !== undefined}
                aria-describedby={
                  errors.description === undefined
                    ? 'knowledge-create-description-hint'
                    : 'knowledge-create-description-error'
                }
                {...register('description')}
              />

              {errors.description === undefined ? (
                <span
                  id="knowledge-create-description-hint"
                  className="knowledge-dialog-field__hint"
                >
                  Briefly explain when this source should be used.
                </span>
              ) : (
                <span
                  id="knowledge-create-description-error"
                  className="knowledge-dialog-field__error"
                  role="alert"
                >
                  {errors.description.message}
                </span>
              )}
            </label>

            <label
              className="knowledge-dialog-field"
              data-invalid={errors.content_type !== undefined}
            >
              <span className="knowledge-dialog-field__label">Content type</span>

              <select
                disabled={pending}
                aria-invalid={errors.content_type !== undefined}
                {...register('content_type')}
              >
                {contentTypes.map((contentType) => (
                  <option value={contentType} key={contentType}>
                    {formatContentType(contentType)}
                  </option>
                ))}
              </select>

              {errors.content_type !== undefined && (
                <span className="knowledge-dialog-field__error" role="alert">
                  {errors.content_type.message}
                </span>
              )}
            </label>

            <label
              className="knowledge-dialog-field"
              data-invalid={errors.visibility !== undefined}
            >
              <span className="knowledge-dialog-field__label">Visibility</span>

              <select
                disabled={pending}
                aria-invalid={errors.visibility !== undefined}
                {...register('visibility')}
              >
                {visibilityOptions.map((visibility) => (
                  <option value={visibility} key={visibility}>
                    {formatKnowledgeVisibility(visibility)}
                  </option>
                ))}
              </select>

              <span className="knowledge-dialog-field__hint">
                Visibility controls who may retrieve information from this document.
              </span>

              {errors.visibility !== undefined && (
                <span className="knowledge-dialog-field__error" role="alert">
                  {errors.visibility.message}
                </span>
              )}
            </label>
          </div>

          <div className="knowledge-dialog-notice">
            <Info size={18} aria-hidden="true" />

            <span>
              This creates document metadata only. It does not create, process, embed, or publish a
              source version.
            </span>
          </div>

          {createDocument.isError && (
            <div className="knowledge-dialog-notice knowledge-dialog-notice--error" role="alert">
              <Info size={18} aria-hidden="true" />

              <span>
                {unconfirmed
                  ? 'The creation result could not be confirmed. Close this dialog and inspect the refreshed library before trying again.'
                  : createDocument.error.message}
              </span>
            </div>
          )}

          <div className="knowledge-confirmation-dialog__actions">
            <button
              type="button"
              className="knowledge-confirmation-dialog__action knowledge-confirmation-dialog__action--outline"
              disabled={pending}
              onClick={requestClose}
            >
              Cancel
            </button>

            <button
              type="submit"
              className="knowledge-confirmation-dialog__action knowledge-confirmation-dialog__action--solid"
              disabled={pending || !isValid || unconfirmed}
            >
              {pending && <LoaderCircle size={18} className="is-spinning" aria-hidden="true" />}

              {pending ? 'Creating…' : 'Create document'}
            </button>
          </div>

          <p
            className="knowledge-confirmation-dialog__status"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {pending ? 'Creating the document. Please wait for confirmation.' : ''}
          </p>
        </form>
      </section>
    </dialog>,
    document.body,
  );
}
