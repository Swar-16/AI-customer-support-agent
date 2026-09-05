from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from packages.knowledge.embeddings.errors import (
    EmbeddingInputBuildError,
    EmbeddingInputValidationError,
)
from packages.knowledge.embeddings.input.base import EmbeddingSourceChunk
from packages.knowledge.embeddings.input.contextual import (
    ContextualEmbeddingInputBuilder,
    ContextualEmbeddingInputConfig,
)


def _source(
    *,
    document_title: str = "Billing Dispute Policy",
    chunk_text: str = (
        "Partial refunds may be issued when only part of an invoice "
        "is disputed successfully."
    ),
    section_title: str | None = "4.4 Refund Calculation",
    section_path: tuple[str, ...] = (
        "Billing Disputes",
        "4.4 Refund Calculation",
    ),
) -> EmbeddingSourceChunk:
    return EmbeddingSourceChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        document_title=document_title,
        chunk_text=chunk_text,
        section_title=section_title,
        section_path=section_path,
    )


class TestContextualEmbeddingInputConfig:
    def test_default_configuration(self) -> None:
        config = ContextualEmbeddingInputConfig()

        assert config.include_document_title is True
        assert config.include_section_path is True
        assert config.include_section_title is True
        assert config.document_label == "Document"
        assert config.section_label == "Section"
        assert config.section_separator == " > "
        assert config.block_separator == "\n\n"
        assert config.max_context_chars is None

    def test_labels_are_trimmed(self) -> None:
        config = ContextualEmbeddingInputConfig(
            document_label="  Document  ",
            section_label="  Section  ",
        )

        assert config.document_label == "Document"
        assert config.section_label == "Section"

    @pytest.mark.parametrize("label", ["", " ", "\t", "\n"])
    def test_blank_document_label_is_rejected_when_enabled(
        self,
        label: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="document_label must not be blank",
        ):
            ContextualEmbeddingInputConfig(
                include_document_title=True,
                document_label=label,
            )

    def test_blank_document_label_is_allowed_when_document_context_disabled(
        self,
    ) -> None:
        config = ContextualEmbeddingInputConfig(
            include_document_title=False,
            document_label=" ",
        )

        assert config.document_label == ""

    @pytest.mark.parametrize("label", ["", " ", "\t", "\n"])
    def test_blank_section_label_is_rejected_when_section_context_enabled(
        self,
        label: str,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="section_label must not be blank",
        ):
            ContextualEmbeddingInputConfig(
                section_label=label,
            )

    def test_blank_section_label_is_allowed_when_section_context_disabled(
        self,
    ) -> None:
        config = ContextualEmbeddingInputConfig(
            include_section_path=False,
            include_section_title=False,
            section_label=" ",
        )

        assert config.section_label == ""

    def test_empty_section_separator_is_rejected(self) -> None:
        with pytest.raises(
            ValueError,
            match="section_separator must not be empty",
        ):
            ContextualEmbeddingInputConfig(
                section_separator="",
            )

    def test_empty_block_separator_is_rejected(self) -> None:
        with pytest.raises(
            ValueError,
            match="block_separator must not be empty",
        ):
            ContextualEmbeddingInputConfig(
                block_separator="",
            )

    @pytest.mark.parametrize("value", [0, -1, -100])
    def test_non_positive_context_budget_is_rejected(
        self,
        value: int,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="max_context_chars must be greater than zero",
        ):
            ContextualEmbeddingInputConfig(
                max_context_chars=value,
            )

    def test_fingerprint_is_deterministic(self) -> None:
        first = ContextualEmbeddingInputConfig()
        second = ContextualEmbeddingInputConfig()

        assert first.fingerprint() == second.fingerprint()

    def test_fingerprint_changes_when_behavior_changes(self) -> None:
        first = ContextualEmbeddingInputConfig()
        second = ContextualEmbeddingInputConfig(
            include_document_title=False,
        )

        assert first.fingerprint() != second.fingerprint()

    def test_unicode_configuration_fingerprint_is_deterministic(self) -> None:
        config = ContextualEmbeddingInputConfig(
            section_separator=" → ",
        )

        first = config.fingerprint()
        second = config.fingerprint()

        assert first == second
        assert len(first) == 64


class TestContextualEmbeddingInputBuilderDescriptor:
    def test_descriptor_has_expected_strategy_identity(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        descriptor = builder.descriptor

        assert descriptor.strategy_id == "contextual-chunk"
        assert descriptor.version == "1.0.0"
        assert descriptor.config_fingerprint == builder.config.fingerprint()

    def test_descriptor_changes_when_config_changes(self) -> None:
        first = ContextualEmbeddingInputBuilder()

        second = ContextualEmbeddingInputBuilder(
            ContextualEmbeddingInputConfig(
                include_document_title=False,
            )
        )

        assert (
            first.descriptor.config_fingerprint
            != second.descriptor.config_fingerprint
        )


class TestContextualEmbeddingInputBuilderRendering:
    def test_builds_expected_contextual_input(self) -> None:
        builder = ContextualEmbeddingInputBuilder()
        source = _source()

        result = builder.build(source)

        expected = (
            "Document: Billing Dispute Policy\n\n"
            "Section: Billing Disputes > 4.4 Refund Calculation\n\n"
            "Partial refunds may be issued when only part of an invoice "
            "is disputed successfully."
        )

        assert result.chunk_id == source.chunk_id
        assert result.text == expected

    def test_document_title_can_be_disabled(self) -> None:
        builder = ContextualEmbeddingInputBuilder(
            ContextualEmbeddingInputConfig(
                include_document_title=False,
            )
        )

        result = builder.build(_source())

        assert result.text == (
            "Section: Billing Disputes > 4.4 Refund Calculation\n\n"
            "Partial refunds may be issued when only part of an invoice "
            "is disputed successfully."
        )

    def test_section_path_can_be_disabled(self) -> None:
        builder = ContextualEmbeddingInputBuilder(
            ContextualEmbeddingInputConfig(
                include_section_path=False,
                include_section_title=True,
            )
        )

        result = builder.build(_source())

        assert result.text == (
            "Document: Billing Dispute Policy\n\n"
            "Section: 4.4 Refund Calculation\n\n"
            "Partial refunds may be issued when only part of an invoice "
            "is disputed successfully."
        )

    def test_section_title_can_be_disabled(self) -> None:
        builder = ContextualEmbeddingInputBuilder(
            ContextualEmbeddingInputConfig(
                include_section_path=True,
                include_section_title=False,
            )
        )

        result = builder.build(_source())

        assert result.text == (
            "Document: Billing Dispute Policy\n\n"
            "Section: Billing Disputes > 4.4 Refund Calculation\n\n"
            "Partial refunds may be issued when only part of an invoice "
            "is disputed successfully."
        )

    def test_all_context_can_be_disabled(self) -> None:
        builder = ContextualEmbeddingInputBuilder(
            ContextualEmbeddingInputConfig(
                include_document_title=False,
                include_section_path=False,
                include_section_title=False,
            )
        )

        source = _source()

        result = builder.build(source)

        assert result.text == source.chunk_text

    def test_custom_labels_are_rendered(self) -> None:
        builder = ContextualEmbeddingInputBuilder(
            ContextualEmbeddingInputConfig(
                document_label="Policy",
                section_label="Topic",
            )
        )

        result = builder.build(_source())

        assert result.text.startswith(
            "Policy: Billing Dispute Policy\n\n"
            "Topic: Billing Disputes > 4.4 Refund Calculation"
        )

    def test_custom_separators_are_rendered(self) -> None:
        builder = ContextualEmbeddingInputBuilder(
            ContextualEmbeddingInputConfig(
                section_separator=" / ",
                block_separator="\n",
            )
        )

        result = builder.build(_source())

        assert result.text == (
            "Document: Billing Dispute Policy\n"
            "Section: Billing Disputes / 4.4 Refund Calculation\n"
            "Partial refunds may be issued when only part of an invoice "
            "is disputed successfully."
        )


class TestSectionContext:
    def test_duplicate_section_title_at_end_of_path_is_not_repeated(
        self,
    ) -> None:
        builder = ContextualEmbeddingInputBuilder()

        source = _source(
            section_path=(
                "Billing Disputes",
                "4.4 Refund Calculation",
            ),
            section_title="4.4 Refund Calculation",
        )

        result = builder.build(source)

        assert (
            "Section: Billing Disputes > 4.4 Refund Calculation"
            in result.text
        )

        assert result.text.count("4.4 Refund Calculation") == 1

    def test_adjacent_duplicate_path_segments_are_collapsed(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        source = _source(
            section_path=(
                "Billing",
                "Refunds",
                "Refunds",
            ),
            section_title=None,
        )

        result = builder.build(source)

        assert "Section: Billing > Refunds" in result.text
        assert "Refunds > Refunds" not in result.text

    def test_non_adjacent_repeated_path_segment_is_preserved(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        source = _source(
            section_path=(
                "FAQ",
                "Account",
                "FAQ",
            ),
            section_title=None,
        )

        result = builder.build(source)

        assert "Section: FAQ > Account > FAQ" in result.text

    def test_empty_section_context_is_omitted(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        source = _source(
            section_path=(),
            section_title=None,
        )

        result = builder.build(source)

        assert result.text == (
            "Document: Billing Dispute Policy\n\n"
            "Partial refunds may be issued when only part of an invoice "
            "is disputed successfully."
        )

    def test_whitespace_only_section_parts_do_not_render(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        source = _source(
            section_path=(" ", "\t", "Refunds", " "),
            section_title=None,
        )

        result = builder.build(source)

        assert "Section: Refunds" in result.text

    def test_section_title_is_appended_when_not_already_last_path_item(
        self,
    ) -> None:
        builder = ContextualEmbeddingInputBuilder()

        source = _source(
            section_path=("Billing",),
            section_title="Refund Calculation",
        )

        result = builder.build(source)

        assert "Section: Billing > Refund Calculation" in result.text


class TestContextBudget:
    def test_context_budget_does_not_truncate_chunk_text(self) -> None:
        chunk_text = (
            "This canonical semantic content must remain completely intact."
        )

        builder = ContextualEmbeddingInputBuilder(
            ContextualEmbeddingInputConfig(
                max_context_chars=1,
            )
        )

        result = builder.build(
            _source(
                chunk_text=chunk_text,
            )
        )

        assert result.text == chunk_text

    def test_context_block_is_kept_when_within_budget(self) -> None:
        block = "Document: Billing Dispute Policy"

        builder = ContextualEmbeddingInputBuilder(
            ContextualEmbeddingInputConfig(
                include_section_path=False,
                include_section_title=False,
                max_context_chars=len(block),
            )
        )

        result = builder.build(_source())

        assert result.text.startswith(block + "\n\n")

    def test_context_block_is_dropped_when_over_budget(self) -> None:
        block = "Document: Billing Dispute Policy"

        builder = ContextualEmbeddingInputBuilder(
            ContextualEmbeddingInputConfig(
                include_section_path=False,
                include_section_title=False,
                max_context_chars=len(block) - 1,
            )
        )

        source = _source()

        result = builder.build(source)

        assert result.text == source.chunk_text

    def test_budget_accounts_for_separator_between_context_blocks(
        self,
    ) -> None:
        document_block = "Document: Billing Dispute Policy"
        section_block = (
            "Section: Billing Disputes > 4.4 Refund Calculation"
        )

        exact_budget = (
            len(document_block)
            + len("\n\n")
            + len(section_block)
        )

        builder = ContextualEmbeddingInputBuilder(
            ContextualEmbeddingInputConfig(
                max_context_chars=exact_budget,
            )
        )

        result = builder.build(_source())

        assert document_block in result.text
        assert section_block in result.text

    def test_context_blocks_are_dropped_individually_when_they_do_not_fit(
        self,
    ) -> None:
        document_block = "Document: Billing Dispute Policy"

        builder = ContextualEmbeddingInputBuilder(
            ContextualEmbeddingInputConfig(
                max_context_chars=len(document_block),
            )
        )

        result = builder.build(_source())

        assert result.text.startswith(document_block + "\n\n")
        assert "Section:" not in result.text


class TestFingerprinting:
    def test_fingerprint_matches_exact_rendered_utf8_text(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        result = builder.build(_source())

        expected = hashlib.sha256(
            result.text.encode("utf-8")
        ).hexdigest()

        assert result.input_fingerprint == expected

    def test_same_source_produces_same_text_and_fingerprint(self) -> None:
        builder = ContextualEmbeddingInputBuilder()
        source = _source()

        first = builder.build(source)
        second = builder.build(source)

        assert first.text == second.text
        assert first.input_fingerprint == second.input_fingerprint

    def test_different_chunk_content_changes_fingerprint(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        first = builder.build(
            _source(
                chunk_text="Refunds may be issued.",
            )
        )
        second = builder.build(
            _source(
                chunk_text="Refunds may be denied.",
            )
        )

        assert first.input_fingerprint != second.input_fingerprint

    def test_different_document_context_changes_fingerprint(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        first = builder.build(
            _source(
                document_title="Refund Policy",
            )
        )
        second = builder.build(
            _source(
                document_title="Billing Policy",
            )
        )

        assert first.input_fingerprint != second.input_fingerprint

    def test_different_section_context_changes_fingerprint(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        first = builder.build(
            _source(
                section_path=("Refunds",),
                section_title=None,
            )
        )
        second = builder.build(
            _source(
                section_path=("Payments",),
                section_title=None,
            )
        )

        assert first.input_fingerprint != second.input_fingerprint

    def test_unicode_is_preserved_in_fingerprint_input(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        source = _source(
            chunk_text="Refunds commonly take 3–7 business days.",
        )

        result = builder.build(source)

        assert "3–7 business days" in result.text

        assert result.input_fingerprint == hashlib.sha256(
            result.text.encode("utf-8")
        ).hexdigest()


class TestCanonicalContentPreservation:
    def test_internal_unicode_is_not_normalized_or_replaced(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        source = _source(
            chunk_text=(
                "Amount − Fee = Refund. "
                "Customer’s account may require verification."
            )
        )

        result = builder.build(source)

        assert "−" in result.text
        assert "Customer’s" in result.text

    def test_internal_chunk_whitespace_is_preserved(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        source = _source(
            chunk_text="First line.\n\nSecond line.",
        )

        result = builder.build(source)

        assert result.text.endswith(
            "First line.\n\nSecond line."
        )


class TestFailureTranslation:
    def test_validation_error_is_not_wrapped(self) -> None:
        builder = ContextualEmbeddingInputBuilder()

        source = _source()

        def fail_validation(
            _: EmbeddingSourceChunk,
        ) -> None:
            raise EmbeddingInputValidationError(
                "Expected validation failure.",
                chunk_id=source.chunk_id,
            )

        builder._validate_source = fail_validation  # type: ignore[method-assign]

        with pytest.raises(
            EmbeddingInputValidationError,
            match="Expected validation failure",
        ):
            builder.build(source)

    def test_unexpected_internal_failure_is_wrapped(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        builder = ContextualEmbeddingInputBuilder()
        source = _source()

        def explode(
            _: EmbeddingSourceChunk,
        ) -> list[str]:
            raise RuntimeError("internal implementation failure")

        monkeypatch.setattr(
            builder,
            "_build_context_blocks",
            explode,
        )

        with pytest.raises(
            EmbeddingInputBuildError,
            match=(
                "Unexpected failure while constructing contextual "
                "embedding input"
            ),
        ) as exc_info:
            builder.build(source)

        assert exc_info.value.__cause__ is not None
        assert isinstance(
            exc_info.value.__cause__,
            RuntimeError,
        )

        assert exc_info.value.details["chunk_id"] == source.chunk_id
        assert (
            exc_info.value.details["strategy_id"]
            == "contextual-chunk"
        )