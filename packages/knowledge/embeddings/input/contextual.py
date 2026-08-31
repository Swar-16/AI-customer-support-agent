from __future__ import annotations
import hashlib
import json
from dataclasses import asdict, dataclass

from packages.knowledge.embeddings.errors import EmbeddingInputBuildError, EmbeddingInputValidationError
from packages.knowledge.embeddings.input.base import EmbeddingInputBuilder, EmbeddingSourceChunk
from packages.knowledge.embeddings.models import EmbeddingInputDescriptor, PreparedEmbeddingInput


@dataclass(frozen=True, slots=True)
class ContextualEmbeddingInputConfig:
    """
    Configuration for constructing contextual embedding inputs.

    The configuration is deliberately explicit because any option that changes the model-facing text changes 
    embedding semantics and therefore must be represented in the strategy fingerprint.
    """
    include_document_title: bool = True
    include_section_path: bool = True
    include_section_title: bool = True
    document_label: str = "Document"
    section_label: str = "Section"
    section_separator: str = " > "
    block_separator: str = "\n\n"
    max_context_chars: int | None = None

    def __post_init__(self) -> None:
        document_label = self.document_label.strip()
        section_label = self.section_label.strip()

        if self.include_document_title and not document_label:
            raise ValueError("document_label must not be blank when document title context is enabled.")

        if (self.include_section_path or self.include_section_title) and not section_label:
            raise ValueError("section_label must not be blank when section context is enabled.")

        if not self.section_separator:
            raise ValueError("section_separator must not be empty.")

        if not self.block_separator:
            raise ValueError("block_separator must not be empty.")

        if self.max_context_chars is not None and self.max_context_chars <= 0:
            raise ValueError("max_context_chars must be greater than zero when provided.")

        object.__setattr__(self, "document_label", document_label)
        object.__setattr__(self, "section_label", section_label)

    def fingerprint(self) -> str:
        """
        Return a deterministic fingerprint for all behavior-affecting configuration.

        JSON serialization uses stable ordering so logically identical configuration always produces the same fingerprint.
        """
        payload = json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

        return hashlib.sha256(payload).hexdigest()

class ContextualEmbeddingInputBuilder(EmbeddingInputBuilder):
    """
    Construct deterministic embedding text from canonical chunk content plus stable structural context.

    Example output:

        Document: Billing Dispute Policy

        Section: Billing Disputes > 4.4 Refund Calculation

        Partial refunds may be issued when only part of an invoice is
        disputed successfully.

    The canonical chunk text is never modified in persistence. Context exists only in this derived embedding representation.
    """
    STRATEGY_ID = "contextual-chunk"
    STRATEGY_VERSION = "1.0.0"

    def __init__(self, config: ContextualEmbeddingInputConfig | None = None) -> None:
        self._config = config or ContextualEmbeddingInputConfig()

        self._descriptor = EmbeddingInputDescriptor(
            strategy_id=self.STRATEGY_ID,
            version=self.STRATEGY_VERSION,
            config_fingerprint=self._config.fingerprint(),
        )

    @property
    def descriptor(self) -> EmbeddingInputDescriptor:
        return self._descriptor

    @property
    def config(self) -> ContextualEmbeddingInputConfig:
        return self._config

    def build(self, source: EmbeddingSourceChunk) -> PreparedEmbeddingInput:
        try:
            self._validate_source(source)
            context_blocks = self._build_context_blocks(source)
            if self._config.max_context_chars is not None:
                context_blocks = self._apply_context_budget(context_blocks=context_blocks, max_chars=self._config.max_context_chars)

            text = self._render(context_blocks=context_blocks, chunk_text=source.chunk_text)
            if not text.strip():
                raise EmbeddingInputValidationError(
                    "Embedding input builder produced blank text.",
                    chunk_id=source.chunk_id,
                    strategy_id=self.descriptor.strategy_id,
                )

            fingerprint = self._fingerprint_text(text)

            return PreparedEmbeddingInput(
                chunk_id=source.chunk_id,
                text=text,
                input_fingerprint=fingerprint,
            )

        except EmbeddingInputValidationError:
            raise

        except Exception as exc:
            raise EmbeddingInputBuildError(
                "Unexpected failure while constructing contextual embedding input.",
                chunk_id=source.chunk_id,
                strategy_id=self.descriptor.strategy_id,
            ) from exc

    def _validate_source(self, source: EmbeddingSourceChunk) -> None:
        if not source.chunk_text.strip():
            raise EmbeddingInputValidationError(
                "Embedding source chunk text must not be blank.",
                chunk_id=source.chunk_id,
                strategy_id=self.descriptor.strategy_id,
            )

        if self._config.include_document_title and not source.document_title.strip():
            raise EmbeddingInputValidationError(
                "Document title is required by the configured embedding input strategy.",
                chunk_id=source.chunk_id,
                strategy_id=self.descriptor.strategy_id,
            )

    def _build_context_blocks(self, source: EmbeddingSourceChunk) -> list[str]:
        blocks: list[str] = []

        if self._config.include_document_title:
            blocks.append(f"{self._config.document_label}: {source.document_title}")

        section_context = self._build_section_context(source)
        if section_context is not None:
            blocks.append(f"{self._config.section_label}: {section_context}")

        return blocks

    def _build_section_context(self, source: EmbeddingSourceChunk) -> str | None:
        """
        Build one normalized structural section representation.

        section_path and section_title can overlap. For example:

            section_path:
                ("Billing", "4.4 Refund Calculation")

            section_title:
                "4.4 Refund Calculation"

        We avoid rendering the title twice.
        """
        parts: list[str] = []
        if self._config.include_section_path:
            for part in source.section_path:
                normalized = part.strip()

                if normalized:
                    self._append_unique(parts, normalized)

        if self._config.include_section_title and source.section_title is not None:
            normalized_title = source.section_title.strip()
            if normalized_title:
                self._append_unique(parts, normalized_title)

        if not parts:
            return None

        return self._config.section_separator.join(parts)

    @staticmethod
    def _append_unique(parts: list[str], value: str) -> None:
        """
        Preserve hierarchy while eliminating only adjacent duplicate structural labels.

        A repeated name at a different hierarchy level may be legitimate and therefore must not be removed globally.
        """
        if not parts or parts[-1] != value:
            parts.append(value)

    def _apply_context_budget(self, *, context_blocks: list[str], max_chars: int) -> list[str]:
        """
        Restrict contextual enrichment without truncating canonical chunk text.

        Context is auxiliary. If a provider has an eventual input limit, the canonical chunk body should be preserved before optional context.

        Blocks are retained in priority order until adding another block would exceed the configured context budget.

        We deliberately do not slice a structural label mid-character or mid-heading.
        """
        selected: list[str] = []
        used_chars = 0

        for block in context_blocks:
            additional = len(block)

            if selected:
                additional += len(self._config.block_separator)

            if used_chars + additional > max_chars:
                continue

            selected.append(block)
            used_chars += additional

        return selected

    def _render(self, *, context_blocks: list[str], chunk_text: str) -> str:
        """
        Render the exact model-facing representation.

        This function is intentionally simple and deterministic. Any material formatting change here should result in a strategy version bump.
        """
        normalized_chunk_text = chunk_text.strip()
        if not context_blocks:
            return normalized_chunk_text

        return self._config.block_separator.join([*context_blocks, normalized_chunk_text])

    @staticmethod
    def _fingerprint_text(text: str) -> str:
        """
        Fingerprint the exact UTF-8 model-facing input.

        Do not hash only canonical chunk content. Any change to contextual rendering must invalidate the existing embedding artifact.
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()