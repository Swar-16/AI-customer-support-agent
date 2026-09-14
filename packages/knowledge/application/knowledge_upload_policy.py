# AI-customer-support-agent\packages\knowledge\application\knowledge_upload_policy.py
from __future__ import annotations
import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import PurePath
from types import MappingProxyType
from typing import Final, Mapping

from packages.knowledge.application.exceptions import EmptyKnowledgeUploadError, InvalidKnowledgeUploadEncodingError, InvalidKnowledgeUploadFilenameError
from packages.knowledge.application.exceptions import KnowledgeUploadConfigurationError, KnowledgeUploadTooLargeError, UnsafeKnowledgeUploadContentError
from packages.knowledge.application.exceptions import UnsupportedKnowledgeUploadMediaTypeError, UnsupportedKnowledgeUploadTypeError
from packages.knowledge.domain.enums import KnowledgeSourceType

MAX_UPLOAD_FILENAME_LENGTH: Final = 255
_WINDOWS_RESERVED_NAMES: Final = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
_BIDI_CONTROL_CHARACTERS: Final = frozenset({
    "\u061c", "\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069",
})

_BINARY_SIGNATURES: Final = (
    b"\x7fELF", b"MZ", b"PK\x03\x04", b"%PDF-", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"\x1f\x8b",
)

@dataclass(frozen=True, slots=True)
class KnowledgeUploadFormat:
    source_type: KnowledgeSourceType
    media_types: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.source_type, KnowledgeSourceType):
            raise TypeError("source_type must be a KnowledgeSourceType.")
        if not isinstance(self.media_types, frozenset) or not self.media_types:
            raise TypeError("media_types must be a non-empty frozenset.")
        if not all(isinstance(media_type, str) and media_type and media_type == media_type.strip().casefold() for media_type in self.media_types):
            raise ValueError("media_types must contain normalized, non-empty strings.")

DEFAULT_KNOWLEDGE_UPLOAD_FORMATS: Final[Mapping[str, KnowledgeUploadFormat]] = MappingProxyType(
    {
        ".md": KnowledgeUploadFormat(
            source_type=KnowledgeSourceType.MARKDOWN,
            media_types=frozenset({"text/markdown", "text/plain"}),
        ),
        ".txt": KnowledgeUploadFormat(
            source_type=KnowledgeSourceType.PLAIN_TEXT,
            media_types=frozenset({"text/plain"}),
        ),
    }
)

@dataclass(frozen=True, slots=True)
class ValidatedKnowledgeUpload:
    filename: str
    extension: str
    media_type: str
    source_type: KnowledgeSourceType
    source_content: str
    uploaded_size_bytes: int
    upload_hash: str
    content_hash: str

class KnowledgeUploadPolicy:
    """
    Validate uploaded knowledge bytes without persistence or HTTP concerns.

    Valid content is returned as inert text. This component never opens a client path, writes a file,
    invokes a shell, imports uploaded content, or interprets Markdown/commands as executable instructions.
    """
    def __init__(self, *, max_upload_bytes: int, formats: Mapping[str, KnowledgeUploadFormat] | None = None) -> None:
        if not isinstance(max_upload_bytes, int) or isinstance(max_upload_bytes, bool) or max_upload_bytes <= 0:
            raise KnowledgeUploadConfigurationError("max_upload_bytes must be a positive integer.")

        configured_formats = DEFAULT_KNOWLEDGE_UPLOAD_FORMATS if formats is None else formats
        normalized_formats = _normalize_format_registry(configured_formats)
        self._max_upload_bytes = max_upload_bytes
        self._formats = MappingProxyType(normalized_formats)

    @property
    def max_upload_bytes(self) -> int:
        return self._max_upload_bytes

    @property
    def allowed_extensions(self) -> tuple[str, ...]:
        return tuple(sorted(self._formats))

    def validate(self, *, filename: str, media_type: str, content: bytes) -> ValidatedKnowledgeUpload:
        if not isinstance(filename, str):
            raise TypeError("filename must be a string.")
        
        if not isinstance(media_type, str):
            raise TypeError("media_type must be a string.")
        
        if not isinstance(content, bytes):
            raise TypeError("content must be bytes.")

        safe_filename = _validate_filename(filename)
        extension = PurePath(safe_filename).suffix.casefold()
        format_ = self._formats.get(extension)
        if format_ is None:
            raise UnsupportedKnowledgeUploadTypeError(filename=safe_filename, allowed_extensions=self.allowed_extensions)

        normalized_media_type = _normalize_media_type(media_type)
        if normalized_media_type not in format_.media_types:
            raise UnsupportedKnowledgeUploadMediaTypeError(
                filename=safe_filename,
                media_type=normalized_media_type or None,
                allowed_media_types=tuple(sorted(format_.media_types)),
            )

        uploaded_size_bytes = len(content)
        if uploaded_size_bytes == 0:
            raise EmptyKnowledgeUploadError()
        
        if uploaded_size_bytes > self._max_upload_bytes:
            raise KnowledgeUploadTooLargeError(actual_bytes=uploaded_size_bytes, maximum_bytes=self._max_upload_bytes)

        _reject_known_binary_content(content)

        try:
            decoded = content.decode("utf-8-sig", errors="strict")
            
        except UnicodeDecodeError as exc:
            raise InvalidKnowledgeUploadEncodingError() from exc

        source_content = decoded.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not source_content or not _contains_meaningful_text(source_content):
            raise EmptyKnowledgeUploadError()

        _validate_text_characters(source_content)

        return ValidatedKnowledgeUpload(
            filename=safe_filename,
            extension=extension,
            media_type=normalized_media_type,
            source_type=format_.source_type,
            source_content=source_content,
            uploaded_size_bytes=uploaded_size_bytes,
            upload_hash=hashlib.sha256(content).hexdigest(),
            content_hash=hashlib.sha256(source_content.encode("utf-8")).hexdigest(),
        )


def _normalize_format_registry(formats: Mapping[str, KnowledgeUploadFormat]) -> dict[str, KnowledgeUploadFormat]:
    if not isinstance(formats, Mapping) or not formats:
        raise KnowledgeUploadConfigurationError("formats must be a non-empty mapping.")

    normalized: dict[str, KnowledgeUploadFormat] = {}
    for extension, format_ in formats.items():
        if not isinstance(extension, str):
            raise KnowledgeUploadConfigurationError("Upload format extensions must be strings.")
        
        normalized_extension = extension.strip().casefold()
        if not normalized_extension.startswith(".") or len(normalized_extension) < 2 or "/" in normalized_extension or "\\" in normalized_extension:
            raise KnowledgeUploadConfigurationError(f"Invalid upload extension configuration: {extension!r}.")
        
        if not isinstance(format_, KnowledgeUploadFormat):
            raise KnowledgeUploadConfigurationError("Each upload format must be a KnowledgeUploadFormat.")
        
        if normalized_extension in normalized:
            raise KnowledgeUploadConfigurationError(f"Duplicate upload extension: {normalized_extension!r}.")
        
        normalized[normalized_extension] = format_

    return normalized

def _normalize_media_type(media_type: str) -> str:
    return media_type.partition(";")[0].strip().casefold()

def _validate_filename(filename: str) -> str:
    normalized = unicodedata.normalize("NFKC", filename).strip()
    if not normalized:
        raise InvalidKnowledgeUploadFilenameError("Filename must not be blank.")
    
    if len(normalized) > MAX_UPLOAD_FILENAME_LENGTH:
        raise InvalidKnowledgeUploadFilenameError(f"Filename must not exceed {MAX_UPLOAD_FILENAME_LENGTH} characters.")
    
    if normalized in {".", ".."} or normalized.endswith((".", " ")):
        raise InvalidKnowledgeUploadFilenameError("Filename is not safe.")
    
    if "/" in normalized or "\\" in normalized or ":" in normalized:
        raise InvalidKnowledgeUploadFilenameError("Filename must not contain path components.")
    
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise InvalidKnowledgeUploadFilenameError("Filename contains unsupported control characters.")

    path = PurePath(normalized)
    if path.name != normalized or not path.stem.strip(". "):
        raise InvalidKnowledgeUploadFilenameError("Filename is not safe.")
    
    if path.stem.casefold() in _WINDOWS_RESERVED_NAMES:
        raise InvalidKnowledgeUploadFilenameError("Filename uses a reserved operating-system name.")

    return normalized

def _reject_known_binary_content(content: bytes) -> None:
    if b"\x00" in content:
        raise UnsafeKnowledgeUploadContentError("The uploaded text file contains NUL bytes.")
    
    if any(content.startswith(signature) for signature in _BINARY_SIGNATURES):
        raise UnsafeKnowledgeUploadContentError("The uploaded file has a binary or unsupported file signature.")

def _validate_text_characters(content: str) -> None:
    for character in content:
        if character in _BIDI_CONTROL_CHARACTERS:
            raise UnsafeKnowledgeUploadContentError("The uploaded text contains bidirectional control characters.")
        
        if unicodedata.category(character) == "Cc" and character not in {"\t", "\n", "\r",}:
            raise UnsafeKnowledgeUploadContentError("The uploaded text contains unsupported control characters.")

def _contains_meaningful_text(content: str) -> bool:
    return any(not character.isspace() and not unicodedata.category(character).startswith("C") for character in content)