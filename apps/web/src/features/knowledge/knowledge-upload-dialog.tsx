// apps/web/src/features/knowledge/knowledge-upload-dialog.tsx

import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Info, LoaderCircle, Upload, X } from 'lucide-react';
import { useForm, type SubmitHandler } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

import {
  createKnowledgeDocumentInputSchema,
  type KnowledgeContentType,
  type KnowledgeVisibility,
} from './knowledge-contract';
import { formatContentType, formatKnowledgeVisibility } from './knowledge-formatters';
import { KnowledgeUploadDropzone } from './knowledge-upload-dropzone';
import { useUploadKnowledgeDocument } from './knowledge-queries';

import './knowledge-dialog.css';

interface KnowledgeUploadDialogProps {
  readonly open: boolean;
  readonly onClose: () => void;

  readonly onUploaded: (documentId: string) => void;
}

type UploadDocumentFormInput = z.input<typeof createKnowledgeDocumentInputSchema>;

type UploadDocumentFormOutput = z.output<typeof createKnowledgeDocumentInputSchema>;

const contentTypes = [
  'policy',
  'faq',
  'procedure',
  'guide',
  'reference',
  'other',
] satisfies readonly KnowledgeContentType[];

const visibilityOptions = ['customer', 'internal', 'both'] satisfies readonly KnowledgeVisibility[];

const defaultValues: UploadDocumentFormInput = {
  title: '',
  description: '',
  content_type: 'faq',
  visibility: 'customer',
};

export function KnowledgeUploadDialog({ open, onClose, onUploaded }: KnowledgeUploadDialogProps) {
  const titleId = useId();
  const descriptionId = useId();

  const dialogRef = useRef<HTMLDialogElement>(null);

  const triggerRef = useRef<HTMLElement | null>(null);

  const previouslyOpenRef = useRef(false);

  const [file, setFile] = useState<File | null>(null);

  const [fileRequiredError, setFileRequiredError] = useState(false);

  const uploadDocument = useUploadKnowledgeDocument();

  const {
    register,
    handleSubmit,
    reset,
    setFocus,
    formState: { errors, isValid },
  } = useForm<UploadDocumentFormInput, unknown, UploadDocumentFormOutput>({
    resolver: zodResolver(createKnowledgeDocumentInputSchema),
    mode: 'onChange',
    defaultValues,
  });

  const pending = uploadDocument.isPending;

  const unconfirmed =
    uploadDocument.isError &&
    (uploadDocument.error.kind === 'network' || uploadDocument.error.kind === 'timeout');

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

  function clearDialogState() {
    reset(defaultValues);
    setFile(null);
    setFileRequiredError(false);
    uploadDocument.reset();
  }

  function requestClose() {
    if (pending) {
      return;
    }

    clearDialogState();
    onClose();
  }

  function updateFile(selectedFile: File | null) {
    setFile(selectedFile);

    if (selectedFile !== null) {
      setFileRequiredError(false);
    }
  }

  const submit: SubmitHandler<UploadDocumentFormOutput> = (values) => {
    if (pending || unconfirmed) {
      return;
    }

    if (file === null) {
      setFileRequiredError(true);
      return;
    }

    setFileRequiredError(false);

    const normalizedDescription = values.description?.trim() || null;

    uploadDocument.mutate(
      {
        file,
        title: values.title,
        description: normalizedDescription,
        content_type: values.content_type,
        visibility: values.visibility,
      },
      {
        onSuccess: (response) => {
          clearDialogState();

          onUploaded(response.document_id);
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
      className="knowledge-confirmation-dialog knowledge-upload-dialog"
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
      <section className="knowledge-confirmation-dialog__card knowledge-upload-dialog__card">
        <div className="knowledge-confirmation-dialog__topline">
          <span className="knowledge-confirmation-dialog__icon" aria-hidden="true">
            <Upload size={25} />
          </span>

          <button
            type="button"
            className="knowledge-confirmation-dialog__dismiss"
            aria-label="Close upload document dialog"
            disabled={pending}
            onClick={requestClose}
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        <div className="knowledge-confirmation-dialog__copy">
          <h2 id={titleId} tabIndex={-1}>
            Upload a knowledge document
          </h2>

          <p id={descriptionId}>
            Upload a text source and create its document identity and first immutable version
            atomically.
          </p>
        </div>

        <form
          className="knowledge-upload-dialog__form"
          noValidate
          onSubmit={(event) => {
            void handleSubmit(submit)(event);
          }}
        >
          <div className="knowledge-dialog-fields">
            <div className="knowledge-dialog-field" data-invalid={fileRequiredError}>
              <span className="knowledge-dialog-field__label">Source file</span>

              <KnowledgeUploadDropzone file={file} disabled={pending} onFileChange={updateFile} />

              {fileRequiredError && (
                <span className="knowledge-dialog-field__error" role="alert">
                  Select a valid knowledge file before uploading.
                </span>
              )}
            </div>

            <label className="knowledge-dialog-field" data-invalid={errors.title !== undefined}>
              <span className="knowledge-dialog-field__label">Title</span>

              <input
                type="text"
                autoComplete="off"
                maxLength={300}
                disabled={pending}
                aria-invalid={errors.title !== undefined}
                aria-describedby={
                  errors.title === undefined ? undefined : 'knowledge-upload-title-error'
                }
                {...register('title')}
              />

              {errors.title !== undefined && (
                <span
                  id="knowledge-upload-title-error"
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
                    ? 'knowledge-upload-description-hint'
                    : 'knowledge-upload-description-error'
                }
                {...register('description')}
              />

              {errors.description === undefined ? (
                <span
                  id="knowledge-upload-description-hint"
                  className="knowledge-dialog-field__hint"
                >
                  Explain when this source should answer a customer or support-agent question.
                </span>
              ) : (
                <span
                  id="knowledge-upload-description-error"
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
              Uploading creates the document and its first immutable draft version. Processing,
              embedding, and publishing remain separate controlled actions.
            </span>
          </div>

          {uploadDocument.isError && (
            <div className="knowledge-dialog-notice knowledge-dialog-notice--error" role="alert">
              <Info size={18} aria-hidden="true" />

              <div>
                <span>
                  {unconfirmed
                    ? 'The upload result could not be confirmed. Close this dialog and inspect the refreshed library before trying again.'
                    : uploadDocument.error.message}
                </span>

                {uploadDocument.error.traceId !== null && (
                  <small>
                    Reference: <code>{uploadDocument.error.traceId}</code>
                  </small>
                )}
              </div>
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
              disabled={pending || unconfirmed || !isValid || file === null}
            >
              {pending && <LoaderCircle size={16} className="is-spinning" aria-hidden="true" />}

              <span>{pending ? 'Uploading…' : 'Upload document'}</span>
            </button>
          </div>

          <p
            className="knowledge-confirmation-dialog__status"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {pending ? 'Uploading the document. Please wait for server confirmation.' : ''}
          </p>
        </form>
      </section>
    </dialog>,
    document.body,
  );
}
