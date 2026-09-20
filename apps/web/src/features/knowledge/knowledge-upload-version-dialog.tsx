// apps/web/src/features/knowledge/knowledge-upload-version-dialog.tsx

import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { FileUp, Info, LoaderCircle, X } from 'lucide-react';

import { KnowledgeUploadDropzone } from './knowledge-upload-dropzone';
import { useUploadKnowledgeVersion } from './knowledge-queries';

import './knowledge-dialog.css';

interface KnowledgeUploadVersionDialogProps {
  readonly open: boolean;
  readonly documentId: string;
  readonly documentTitle: string;
  readonly onClose: () => void;

  readonly onUploaded: (versionId: string) => void;
}

export function KnowledgeUploadVersionDialog({
  open,
  documentId,
  documentTitle,
  onClose,
  onUploaded,
}: KnowledgeUploadVersionDialogProps) {
  const titleId = useId();
  const descriptionId = useId();

  const dialogRef = useRef<HTMLDialogElement>(null);

  const headingRef = useRef<HTMLHeadingElement>(null);

  const triggerRef = useRef<HTMLElement | null>(null);

  const previouslyOpenRef = useRef(false);

  const [file, setFile] = useState<File | null>(null);

  const [fileRequiredError, setFileRequiredError] = useState(false);

  const uploadVersion = useUploadKnowledgeVersion();

  const pending = uploadVersion.isPending;

  const unconfirmed =
    uploadVersion.isError &&
    (uploadVersion.error.kind === 'network' || uploadVersion.error.kind === 'timeout');

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
        headingRef.current?.focus({
          preventScroll: true,
        });
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
  }, [open]);

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
    setFile(null);
    setFileRequiredError(false);
    uploadVersion.reset();
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

    if (uploadVersion.isError) {
      uploadVersion.reset();
    }
  }

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (pending || unconfirmed) {
      return;
    }

    if (file === null) {
      setFileRequiredError(true);
      return;
    }

    setFileRequiredError(false);

    uploadVersion.mutate(
      {
        documentId,
        file,
      },
      {
        onSuccess: (response) => {
          clearDialogState();

          onUploaded(response.version_id);
        },
      },
    );
  }

  if (!open) {
    return null;
  }

  return createPortal(
    <dialog
      ref={dialogRef}
      className="knowledge-confirmation-dialog knowledge-upload-version-dialog"
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
      <section className="knowledge-confirmation-dialog__card knowledge-upload-version-dialog__card">
        <div className="knowledge-confirmation-dialog__topline">
          <span className="knowledge-confirmation-dialog__icon" aria-hidden="true">
            <FileUp size={25} />
          </span>

          <button
            type="button"
            className="knowledge-confirmation-dialog__dismiss"
            aria-label="Close upload version dialog"
            disabled={pending}
            onClick={requestClose}
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        <div className="knowledge-confirmation-dialog__copy">
          <h2 ref={headingRef} id={titleId} tabIndex={-1}>
            Upload a new version
          </h2>

          <p id={descriptionId}>
            Add a new immutable source version to <strong>{documentTitle}</strong>.
          </p>
        </div>

        <form className="knowledge-upload-version-dialog__form" noValidate onSubmit={submit}>
          <div className="knowledge-dialog-field" data-invalid={fileRequiredError}>
            <span className="knowledge-dialog-field__label">Source file</span>

            <KnowledgeUploadDropzone file={file} disabled={pending} onFileChange={updateFile} />

            {fileRequiredError && (
              <span className="knowledge-dialog-field__error" role="alert">
                Select a valid Markdown or plain-text file before uploading.
              </span>
            )}
          </div>

          <div className="knowledge-dialog-notice">
            <Info size={18} aria-hidden="true" />

            <span>
              A successful upload creates a new immutable draft version. Processing, embedding, and
              publication remain separate controlled actions.
            </span>
          </div>

          {uploadVersion.isError && (
            <div className="knowledge-dialog-notice knowledge-dialog-notice--error" role="alert">
              <Info size={18} aria-hidden="true" />

              <div>
                <span>
                  {unconfirmed
                    ? 'The upload result could not be confirmed. Close this dialog and inspect the refreshed version history before trying again.'
                    : uploadVersion.error.message}
                </span>

                {uploadVersion.error.traceId !== null && (
                  <small>
                    Reference: <code>{uploadVersion.error.traceId}</code>
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
              disabled={pending || unconfirmed || file === null}
            >
              {pending && <LoaderCircle size={16} className="is-spinning" aria-hidden="true" />}

              <span>{pending ? 'Uploading…' : 'Upload version'}</span>
            </button>
          </div>

          <p
            className="knowledge-confirmation-dialog__status"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {pending
              ? 'Uploading the new immutable version. Please wait for server confirmation.'
              : ''}
          </p>
        </form>
      </section>
    </dialog>,
    document.body,
  );
}
