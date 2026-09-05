from __future__ import annotations

from dataclasses import dataclass

import pytest

from packages.knowledge.domain.enums import (
    KnowledgeSourceType,
)
from packages.knowledge.ingestion.models import (
    ParsedDocument,
)
from packages.knowledge.ingestion.normalization.base import (
    BaseDocumentNormalizer,
    DocumentNormalizer,
    NormalizerDescriptor,
)
from packages.knowledge.ingestion.normalization.errors import (
    KnowledgeNormalizerConfigurationError,
    UnsupportedKnowledgeNormalizationSourceTypeError,
)
from packages.knowledge.ingestion.normalization.models import (
    NormalizedDocument,
)
from packages.knowledge.ingestion.normalization.resolver import (
    DefaultDocumentNormalizerResolver,
)


@dataclass(frozen=True)
class StubNormalizer(
    BaseDocumentNormalizer
):
    normalizer_descriptor: NormalizerDescriptor
    source_types: frozenset[
        KnowledgeSourceType
    ]

    @property
    def descriptor(
        self,
    ) -> NormalizerDescriptor:
        return self.normalizer_descriptor

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return self.source_types

    def normalize(
        self,
        document: ParsedDocument,
    ) -> NormalizedDocument:
        raise NotImplementedError


class InvalidNormalizer:
    pass


class InconsistentSupportsNormalizer(
    BaseDocumentNormalizer
):
    @property
    def descriptor(
        self,
    ) -> NormalizerDescriptor:
        return NormalizerDescriptor(
            strategy_id=(
                "inconsistent-normalizer"
            ),
            version="1.0.0",
        )

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return frozenset({
            KnowledgeSourceType.MARKDOWN,
        })

    def supports(
        self,
        source_type: KnowledgeSourceType,
    ) -> bool:
        return False

    def normalize(
        self,
        document: ParsedDocument,
    ) -> NormalizedDocument:
        raise NotImplementedError


class TestDefaultDocumentNormalizerResolver:
    def test_resolve_returns_registered_normalizer(
        self,
    ):
        normalizer = StubNormalizer(
            normalizer_descriptor=(
                NormalizerDescriptor(
                    strategy_id=(
                        "markdown-semantic"
                    ),
                    version="1.0.0",
                )
            ),
            source_types=frozenset({
                KnowledgeSourceType.MARKDOWN,
            }),
        )

        resolver = (
            DefaultDocumentNormalizerResolver(
                [normalizer]
            )
        )

        resolved = resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        )

        assert resolved is normalizer

    def test_resolve_preserves_identity(
        self,
    ):
        normalizer = StubNormalizer(
            normalizer_descriptor=(
                NormalizerDescriptor(
                    strategy_id=(
                        "markdown-semantic"
                    ),
                    version="1.0.0",
                )
            ),
            source_types=frozenset({
                KnowledgeSourceType.MARKDOWN,
            }),
        )

        resolver = (
            DefaultDocumentNormalizerResolver(
                [normalizer]
            )
        )

        first = resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        )

        second = resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        )

        assert first is normalizer
        assert second is normalizer
        assert first is second

    def test_multiple_normalizers_can_be_registered(
        self,
    ):
        markdown = StubNormalizer(
            normalizer_descriptor=(
                NormalizerDescriptor(
                    strategy_id=(
                        "markdown-semantic"
                    ),
                    version="1.0.0",
                )
            ),
            source_types=frozenset({
                KnowledgeSourceType.MARKDOWN,
            }),
        )

        plain_text = StubNormalizer(
            normalizer_descriptor=(
                NormalizerDescriptor(
                    strategy_id=(
                        "plain-text-semantic"
                    ),
                    version="1.0.0",
                )
            ),
            source_types=frozenset({
                KnowledgeSourceType.PLAIN_TEXT,
            }),
        )

        resolver = (
            DefaultDocumentNormalizerResolver(
                [
                    markdown,
                    plain_text,
                ]
            )
        )

        assert resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        ) is markdown

        assert resolver.resolve(
            KnowledgeSourceType.PLAIN_TEXT
        ) is plain_text

    def test_one_normalizer_can_support_multiple_source_types(
        self,
    ):
        normalizer = StubNormalizer(
            normalizer_descriptor=(
                NormalizerDescriptor(
                    strategy_id=(
                        "text-family-semantic"
                    ),
                    version="1.0.0",
                )
            ),
            source_types=frozenset({
                KnowledgeSourceType.MARKDOWN,
                KnowledgeSourceType.PLAIN_TEXT,
            }),
        )

        resolver = (
            DefaultDocumentNormalizerResolver(
                [normalizer]
            )
        )

        assert resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        ) is normalizer

        assert resolver.resolve(
            KnowledgeSourceType.PLAIN_TEXT
        ) is normalizer

    def test_supported_source_types_returns_registry_types(
        self,
    ):
        normalizer = StubNormalizer(
            normalizer_descriptor=(
                NormalizerDescriptor(
                    strategy_id="text-semantic",
                    version="1.0.0",
                )
            ),
            source_types=frozenset({
                KnowledgeSourceType.MARKDOWN,
                KnowledgeSourceType.PLAIN_TEXT,
            }),
        )

        resolver = (
            DefaultDocumentNormalizerResolver(
                [normalizer]
            )
        )

        assert (
            resolver.supported_source_types
            == frozenset({
                KnowledgeSourceType.MARKDOWN,
                KnowledgeSourceType.PLAIN_TEXT,
            })
        )

    def test_empty_registry_has_no_supported_types(
        self,
    ):
        resolver = (
            DefaultDocumentNormalizerResolver(
                []
            )
        )

        assert (
            resolver.supported_source_types
            == frozenset()
        )

    def test_supports_returns_true_for_registered_type(
        self,
    ):
        normalizer = StubNormalizer(
            normalizer_descriptor=(
                NormalizerDescriptor(
                    strategy_id=(
                        "markdown-semantic"
                    ),
                    version="1.0.0",
                )
            ),
            source_types=frozenset({
                KnowledgeSourceType.MARKDOWN,
            }),
        )

        resolver = (
            DefaultDocumentNormalizerResolver(
                [normalizer]
            )
        )

        assert resolver.supports(
            KnowledgeSourceType.MARKDOWN
        )

    def test_supports_returns_false_for_unregistered_type(
        self,
    ):
        resolver = (
            DefaultDocumentNormalizerResolver(
                []
            )
        )

        assert not resolver.supports(
            KnowledgeSourceType.PDF
        )

    def test_unsupported_source_type_raises(
        self,
    ):
        resolver = (
            DefaultDocumentNormalizerResolver(
                []
            )
        )

        with pytest.raises(
            UnsupportedKnowledgeNormalizationSourceTypeError
        ) as exc_info:
            resolver.resolve(
                KnowledgeSourceType.PDF
            )

        error = exc_info.value

        assert (
            error.code
            == (
                "KNOWLEDGE_NORMALIZATION_"
                "SOURCE_TYPE_UNSUPPORTED"
            )
        )

        assert (
            error.source_type
            is KnowledgeSourceType.PDF
        )

        assert error.context == {
            "source_type": "pdf",
        }

    def test_resolve_rejects_non_source_type(
        self,
    ):
        resolver = (
            DefaultDocumentNormalizerResolver(
                []
            )
        )

        with pytest.raises(
            TypeError,
            match=(
                "source_type must be "
                "a KnowledgeSourceType"
            ),
        ):
            resolver.resolve(
                "pdf"  # type: ignore[arg-type]
            )

    def test_supports_rejects_non_source_type(
        self,
    ):
        resolver = (
            DefaultDocumentNormalizerResolver(
                []
            )
        )

        with pytest.raises(
            TypeError,
            match=(
                "source_type must be "
                "a KnowledgeSourceType"
            ),
        ):
            resolver.supports(
                "pdf"  # type: ignore[arg-type]
            )

    def test_duplicate_source_type_registration_raises(
        self,
    ):
        first = StubNormalizer(
            normalizer_descriptor=(
                NormalizerDescriptor(
                    strategy_id=(
                        "first-markdown-normalizer"
                    ),
                    version="1.0.0",
                )
            ),
            source_types=frozenset({
                KnowledgeSourceType.MARKDOWN,
            }),
        )

        second = StubNormalizer(
            normalizer_descriptor=(
                NormalizerDescriptor(
                    strategy_id=(
                        "second-markdown-normalizer"
                    ),
                    version="2.0.0",
                )
            ),
            source_types=frozenset({
                KnowledgeSourceType.MARKDOWN,
            }),
        )

        with pytest.raises(
            KnowledgeNormalizerConfigurationError
        ) as exc_info:
            DefaultDocumentNormalizerResolver(
                [
                    first,
                    second,
                ]
            )

        error = exc_info.value

        assert (
            error.code
            == (
                "KNOWLEDGE_NORMALIZER_"
                "CONFIGURATION_ERROR"
            )
        )

        assert (
            error.source_type
            is KnowledgeSourceType.MARKDOWN
        )

        assert (
            error.normalizer_name
            == "second-markdown-normalizer"
        )

    def test_normalizer_without_supported_source_types_raises(
        self,
    ):
        normalizer = StubNormalizer(
            normalizer_descriptor=(
                NormalizerDescriptor(
                    strategy_id="empty",
                    version="1.0.0",
                )
            ),
            source_types=frozenset(),
        )

        with pytest.raises(
            KnowledgeNormalizerConfigurationError,
            match=(
                "must support at least one"
            ),
        ):
            DefaultDocumentNormalizerResolver(
                [normalizer]
            )

    def test_invalid_normalizer_contract_raises(
        self,
    ):
        with pytest.raises(
            KnowledgeNormalizerConfigurationError,
            match="does not satisfy",
        ):
            DefaultDocumentNormalizerResolver(
                [
                    InvalidNormalizer()  # type: ignore[list-item]
                ]
            )

    def test_inconsistent_supports_contract_raises(
        self,
    ):
        normalizer = (
            InconsistentSupportsNormalizer()
        )

        with pytest.raises(
            KnowledgeNormalizerConfigurationError,
            match=(
                "supports\\(\\).*returns False"
            ),
        ):
            DefaultDocumentNormalizerResolver(
                [normalizer]
            )

    def test_resolver_accepts_any_iterable(
        self,
    ):
        normalizer = StubNormalizer(
            normalizer_descriptor=(
                NormalizerDescriptor(
                    strategy_id=(
                        "markdown-semantic"
                    ),
                    version="1.0.0",
                )
            ),
            source_types=frozenset({
                KnowledgeSourceType.MARKDOWN,
            }),
        )

        generator = (
            item
            for item in [normalizer]
        )

        resolver = (
            DefaultDocumentNormalizerResolver(
                generator
            )
        )

        assert resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        ) is normalizer

    def test_resolved_object_satisfies_protocol(
        self,
    ):
        normalizer = StubNormalizer(
            normalizer_descriptor=(
                NormalizerDescriptor(
                    strategy_id=(
                        "markdown-semantic"
                    ),
                    version="1.0.0",
                )
            ),
            source_types=frozenset({
                KnowledgeSourceType.MARKDOWN,
            }),
        )

        resolver = (
            DefaultDocumentNormalizerResolver(
                [normalizer]
            )
        )

        resolved = resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        )

        assert isinstance(
            resolved,
            DocumentNormalizer,
        )