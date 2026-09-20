// apps/web/src/features/knowledge/knowledge-upload-dropzone.tsx

import { useId, useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { Check, FileText, LoaderCircle, UploadCloud, X } from 'lucide-react';

import { formatFileSize } from './knowledge-formatters';

export const DEFAULT_KNOWLEDGE_UPLOAD_MAX_BYTES = 1_048_576;

interface KnowledgeUploadDropzoneProps {
  readonly file: File | null;
  readonly disabled?: boolean;
  readonly maxBytes?: number;

  readonly onFileChange: (file: File | null) => void;
}

type KnowledgeUploadExtension = '.md' | '.txt';

interface UploadFormat {
  readonly mediaTypes: readonly string[];

  readonly fallbackMediaType: string;
}

const uploadFormats: Readonly<Record<KnowledgeUploadExtension, UploadFormat>> = {
  '.md': {
    mediaTypes: ['text/markdown', 'text/plain'],
    fallbackMediaType: 'text/markdown',
  },

  '.txt': {
    mediaTypes: ['text/plain'],
    fallbackMediaType: 'text/plain',
  },
};

function isKnowledgeUploadExtension(value: string): value is KnowledgeUploadExtension {
  return Object.prototype.hasOwnProperty.call(uploadFormats, value);
}

const reservedFilenames = new Set([
  'con',
  'prn',
  'aux',
  'nul',
  'com1',
  'com2',
  'com3',
  'com4',
  'com5',
  'com6',
  'com7',
  'com8',
  'com9',
  'lpt1',
  'lpt2',
  'lpt3',
  'lpt4',
  'lpt5',
  'lpt6',
  'lpt7',
  'lpt8',
  'lpt9',
]);

const bidirectionalControls = new Set([
  '\u061c',
  '\u200e',
  '\u200f',
  '\u202a',
  '\u202b',
  '\u202c',
  '\u202d',
  '\u202e',
  '\u2066',
  '\u2067',
  '\u2068',
  '\u2069',
]);

const knownBinarySignatures = [
  [0x7f, 0x45, 0x4c, 0x46],
  [0x4d, 0x5a],
  [0x50, 0x4b, 0x03, 0x04],
  [0x25, 0x50, 0x44, 0x46, 0x2d],
  [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a],
  [0xff, 0xd8, 0xff],
  [0x1f, 0x8b],
] as const;

function getExtension(filename: string): string {
  const dotIndex = filename.lastIndexOf('.');

  if (dotIndex < 0) {
    return '';
  }

  return filename.slice(dotIndex).toLocaleLowerCase('en-US');
}

function startsWithSignature(content: Uint8Array, signature: readonly number[]): boolean {
  if (content.length < signature.length) {
    return false;
  }

  return signature.every((value, index) => content[index] === value);
}

function validateFilename(filename: string): string | null {
  const normalized = filename.normalize('NFKC').trim();

  if (normalized.length === 0) {
    return 'The file must have a name.';
  }

  if (normalized.length > 255) {
    return 'The filename cannot exceed 255 characters.';
  }

  if (
    normalized === '.' ||
    normalized === '..' ||
    normalized.endsWith('.') ||
    normalized.endsWith(' ')
  ) {
    return 'The filename is not safe.';
  }

  if (normalized.includes('/') || normalized.includes('\\') || normalized.includes(':')) {
    return 'The filename cannot contain path characters.';
  }

  for (const character of normalized) {
    const code = character.codePointAt(0);

    if (code !== undefined && (code < 32 || code === 127)) {
      return 'The filename contains unsupported control characters.';
    }
  }

  const extension = getExtension(normalized);

  const stem = normalized
    .slice(0, normalized.length - extension.length)
    .replace(/[. ]+$/gu, '')
    .toLocaleLowerCase('en-US');

  if (stem.length === 0 || reservedFilenames.has(stem)) {
    return 'The filename uses a reserved or unsafe name.';
  }

  return null;
}

function normalizeMediaType(mediaType: string): string {
  return mediaType.split(';', 1)[0]?.trim().toLocaleLowerCase('en-US') ?? '';
}

function containsUnsafeCharacters(content: string): boolean {
  for (const character of content) {
    if (bidirectionalControls.has(character)) {
      return true;
    }

    const code = character.codePointAt(0);

    if (
      code !== undefined &&
      code < 32 &&
      character !== '\t' &&
      character !== '\n' &&
      character !== '\r'
    ) {
      return true;
    }
  }

  return false;
}

function normalizeMissingMediaType(file: File, mediaType: string): File {
  if (file.type.trim().length > 0) {
    return file;
  }

  return new File([file], file.name, {
    type: mediaType,
    lastModified: file.lastModified,
  });
}

async function validateUploadFile(
  file: File,
  maxBytes: number,
): Promise<
  | {
      readonly ok: true;
      readonly file: File;
    }
  | {
      readonly ok: false;
      readonly message: string;
    }
> {
  const filenameError = validateFilename(file.name);

  if (filenameError !== null) {
    return {
      ok: false,
      message: filenameError,
    };
  }

  const extension = getExtension(file.name);

  if (!isKnowledgeUploadExtension(extension)) {
    return {
      ok: false,
      message: 'Choose a Markdown (.md) or plain-text (.txt) file.',
    };
  }

  const format = uploadFormats[extension];

  if (file.size === 0) {
    return {
      ok: false,
      message: 'The selected file is empty.',
    };
  }

  if (file.size > maxBytes) {
    return {
      ok: false,
      message: `The selected file exceeds the ${formatFileSize(maxBytes)} upload limit.`,
    };
  }

  const normalizedFile = normalizeMissingMediaType(file, format.fallbackMediaType);

  const mediaType = normalizeMediaType(normalizedFile.type);

  if (!format.mediaTypes.includes(mediaType)) {
    return {
      ok: false,
      message: 'The file media type does not match its extension.',
    };
  }

  let bytes: Uint8Array;

  try {
    bytes = new Uint8Array(await normalizedFile.arrayBuffer());
  } catch {
    return {
      ok: false,
      message: 'The selected file could not be read.',
    };
  }

  if (
    bytes.includes(0) ||
    knownBinarySignatures.some((signature) => startsWithSignature(bytes, signature))
  ) {
    return {
      ok: false,
      message: 'Binary content cannot be uploaded as a knowledge text file.',
    };
  }

  let decoded: string;

  try {
    decoded = new TextDecoder('utf-8', {
      fatal: true,
    }).decode(bytes);
  } catch {
    return {
      ok: false,
      message: 'Knowledge files must use valid UTF-8 text encoding.',
    };
  }

  const normalizedContent = decoded
    .replace(/^\uFEFF/u, '')
    .replace(/\r\n/gu, '\n')
    .replace(/\r/gu, '\n')
    .trim();

  if (normalizedContent.length === 0) {
    return {
      ok: false,
      message: 'The selected file does not contain meaningful text.',
    };
  }

  if (containsUnsafeCharacters(normalizedContent)) {
    return {
      ok: false,
      message: 'The selected file contains unsupported control characters.',
    };
  }

  return {
    ok: true,
    file: normalizedFile,
  };
}

export function KnowledgeUploadDropzone({
  file,
  disabled = false,
  maxBytes = DEFAULT_KNOWLEDGE_UPLOAD_MAX_BYTES,
  onFileChange,
}: KnowledgeUploadDropzoneProps) {
  const inputId = useId();

  const inputRef = useRef<HTMLInputElement>(null);

  const validationRevisionRef = useRef(0);

  const [dragActive, setDragActive] = useState(false);

  const [validating, setValidating] = useState(false);

  const [validationMessage, setValidationMessage] = useState<string | null>(null);

  async function selectFile(selectedFile: File) {
    if (disabled || validating) {
      return;
    }

    const revision = validationRevisionRef.current + 1;

    validationRevisionRef.current = revision;

    setValidating(true);
    setValidationMessage(null);
    onFileChange(null);

    const result = await validateUploadFile(selectedFile, maxBytes);

    /*
     * Ignore an older validation result if another file
     * was selected before it completed.
     */
    if (revision !== validationRevisionRef.current) {
      return;
    }

    setValidating(false);

    if (!result.ok) {
      setValidationMessage(result.message);

      if (inputRef.current !== null) {
        inputRef.current.value = '';
      }

      return;
    }

    setValidationMessage(null);
    onFileChange(result.file);
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>) {
    const selectedFile = event.currentTarget.files?.[0];

    if (selectedFile !== undefined) {
      void selectFile(selectedFile);
    }
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();

    if (!disabled && !validating) {
      event.dataTransfer.dropEffect = 'copy';

      setDragActive(true);
    }
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
      return;
    }

    setDragActive(false);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);

    if (disabled || validating) {
      return;
    }

    const selectedFile = event.dataTransfer.files[0];

    if (selectedFile !== undefined) {
      void selectFile(selectedFile);
    }
  }

  function removeFile() {
    if (disabled || validating) {
      return;
    }

    validationRevisionRef.current += 1;

    setValidationMessage(null);
    setValidating(false);
    onFileChange(null);

    if (inputRef.current !== null) {
      inputRef.current.value = '';
    }
  }

  const classes = [
    'knowledge-upload-dropzone',

    dragActive ? 'is-drag-active' : '',

    file !== null ? 'has-file' : '',

    validationMessage !== null ? 'has-error' : '',

    disabled ? 'is-disabled' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className="knowledge-upload-field">
      <div
        className={classes}
        onDragEnter={handleDragOver}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <input
          ref={inputRef}
          id={inputId}
          className="knowledge-visually-hidden"
          type="file"
          accept=".md,.txt,text/markdown,text/plain"
          disabled={disabled || validating}
          onChange={handleInputChange}
        />

        {validating ? (
          <div className="knowledge-upload-dropzone__state">
            <span className="knowledge-upload-dropzone__icon" aria-hidden="true">
              <LoaderCircle size={26} className="is-spinning" />
            </span>

            <strong>Checking the file</strong>

            <p role="status">Validating its type, size, encoding, and text content…</p>
          </div>
        ) : file !== null ? (
          <div className="knowledge-upload-dropzone__selected">
            <span className="knowledge-upload-dropzone__icon" aria-hidden="true">
              <Check size={25} />
            </span>

            <div>
              <strong>{file.name}</strong>

              <span>
                <FileText size={14} aria-hidden="true" />

                {formatFileSize(file.size)}
              </span>
            </div>

            <button
              type="button"
              aria-label={`Remove ${file.name}`}
              disabled={disabled}
              onClick={removeFile}
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        ) : (
          <label
            htmlFor={inputId}
            className="knowledge-upload-dropzone__prompt"
            aria-disabled={disabled}
          >
            <span className="knowledge-upload-dropzone__icon" aria-hidden="true">
              <UploadCloud size={27} />
            </span>

            <strong>Drop a knowledge file here</strong>

            <span>or choose a file</span>

            <small>Markdown or plain text, up to {formatFileSize(maxBytes)}</small>
          </label>
        )}
      </div>

      {validationMessage !== null && (
        <p className="knowledge-upload-field__error" role="alert">
          {validationMessage}
        </p>
      )}
    </div>
  );
}
