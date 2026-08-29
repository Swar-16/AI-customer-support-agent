from __future__ import annotations

import pytest

from packages.knowledge.domain.enums import KnowledgeSourceType
from packages.knowledge.ingestion.chunking.base import (
    ChunkerDescriptor,
)
from packages.knowledge.ingestion.chunking.errors import (
    KnowledgeChunkerConfigurationError,
    UnsupportedKnowledgeChunkingSourceTypeError,
)
from packages.knowledge.ingestion.chunking.resolver import (
    DefaultDocumentChunkerResolver,
)


class StubChunker:
    def __init__(
        self,
        *,
        strategy_id: str,
        supported_source_types: frozenset[
            KnowledgeSourceType
        ],
    ) -> None:
        self._descriptor = ChunkerDescriptor(
            strategy_id=strategy_id,
            version="1.0.0",
            config_fingerprint=None,
        )
        self._supported_source_types = (
            supported_source_types
        )

    @property
    def descriptor(self) -> ChunkerDescriptor:
        return self._descriptor

    @property
    def supported_source_types(
        self,
    ) -> frozenset[KnowledgeSourceType]:
        return self._supported_source_types

    def supports(
        self,
        source_type: KnowledgeSourceType,
    ) -> bool:
        return (
            source_type
            in self._supported_source_types
        )

    def chunk(self, document):
        raise NotImplementedError


class TestResolverConstruction:
    def test_requires_at_least_one_chunker(
        self,
    ) -> None:
        with pytest.raises(
            KnowledgeChunkerConfigurationError,
            match="At least one document chunker",
        ):
            DefaultDocumentChunkerResolver([])

    @pytest.mark.parametrize(
        "value",
        [
            None,
            123,
            object(),
        ],
    )
    def test_chunkers_must_be_iterable(
        self,
        value,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="chunkers must be an iterable",
        ):
            DefaultDocumentChunkerResolver(value)

    @pytest.mark.parametrize(
        "value",
        [
            "chunker",
            b"chunker",
        ],
    )
    def test_string_like_iterables_are_rejected(
        self,
        value,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="chunkers must be an iterable",
        ):
            DefaultDocumentChunkerResolver(value)

    def test_single_chunker_can_support_multiple_source_types(
        self,
    ) -> None:
        chunker = StubChunker(
            strategy_id="generic",
            supported_source_types=frozenset(
                {
                    KnowledgeSourceType.MARKDOWN,
                    KnowledgeSourceType.PLAIN_TEXT,
                }
            ),
        )

        resolver = DefaultDocumentChunkerResolver(
            [chunker]
        )

        assert resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        ) is chunker

        assert resolver.resolve(
            KnowledgeSourceType.PLAIN_TEXT
        ) is chunker

    def test_multiple_non_overlapping_chunkers_allowed(
        self,
    ) -> None:
        markdown = StubChunker(
            strategy_id="markdown",
            supported_source_types=frozenset(
                {
                    KnowledgeSourceType.MARKDOWN,
                }
            ),
        )
        pdf = StubChunker(
            strategy_id="pdf",
            supported_source_types=frozenset(
                {
                    KnowledgeSourceType.PDF,
                }
            ),
        )

        resolver = DefaultDocumentChunkerResolver(
            [markdown, pdf]
        )

        assert resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        ) is markdown

        assert resolver.resolve(
            KnowledgeSourceType.PDF
        ) is pdf

    def test_duplicate_source_type_registration_rejected(
        self,
    ) -> None:
        first = StubChunker(
            strategy_id="first",
            supported_source_types=frozenset(
                {
                    KnowledgeSourceType.MARKDOWN,
                }
            ),
        )
        second = StubChunker(
            strategy_id="second",
            supported_source_types=frozenset(
                {
                    KnowledgeSourceType.MARKDOWN,
                }
            ),
        )

        with pytest.raises(
            KnowledgeChunkerConfigurationError,
            match="Multiple document chunkers",
        ) as exc_info:
            DefaultDocumentChunkerResolver(
                [first, second]
            )

        assert (
            exc_info.value.context["source_type"]
            == KnowledgeSourceType.MARKDOWN.value
        )
        assert (
            exc_info.value.context["chunker_name"]
            == "second"
        )
        assert (
            exc_info.value.context[
                "conflicting_chunker_name"
            ]
            == "first"
        )


class TestResolverLookup:
    def test_supported_source_types_are_exposed(
        self,
    ) -> None:
        resolver = DefaultDocumentChunkerResolver(
            [
                StubChunker(
                    strategy_id="generic",
                    supported_source_types=frozenset(
                        {
                            KnowledgeSourceType.MARKDOWN,
                            KnowledgeSourceType.PLAIN_TEXT,
                        }
                    ),
                )
            ]
        )

        assert resolver.supported_source_types == (
            frozenset(
                {
                    KnowledgeSourceType.MARKDOWN,
                    KnowledgeSourceType.PLAIN_TEXT,
                }
            )
        )

    def test_supported_source_types_are_immutable(
        self,
    ) -> None:
        resolver = DefaultDocumentChunkerResolver(
            [
                StubChunker(
                    strategy_id="markdown",
                    supported_source_types=frozenset(
                        {
                            KnowledgeSourceType.MARKDOWN,
                        }
                    ),
                )
            ]
        )

        assert isinstance(
            resolver.supported_source_types,
            frozenset,
        )

    def test_supports_returns_true_for_configured_type(
        self,
    ) -> None:
        resolver = DefaultDocumentChunkerResolver(
            [
                StubChunker(
                    strategy_id="markdown",
                    supported_source_types=frozenset(
                        {
                            KnowledgeSourceType.MARKDOWN,
                        }
                    ),
                )
            ]
        )

        assert resolver.supports(
            KnowledgeSourceType.MARKDOWN
        )

    def test_supports_returns_false_for_unconfigured_type(
        self,
    ) -> None:
        resolver = DefaultDocumentChunkerResolver(
            [
                StubChunker(
                    strategy_id="markdown",
                    supported_source_types=frozenset(
                        {
                            KnowledgeSourceType.MARKDOWN,
                        }
                    ),
                )
            ]
        )

        assert not resolver.supports(
            KnowledgeSourceType.PDF
        )

    @pytest.mark.parametrize(
        "value",
        [
            "markdown",
            None,
            123,
        ],
    )
    def test_supports_rejects_invalid_source_type(
        self,
        value,
    ) -> None:
        resolver = DefaultDocumentChunkerResolver(
            [
                StubChunker(
                    strategy_id="markdown",
                    supported_source_types=frozenset(
                        {
                            KnowledgeSourceType.MARKDOWN,
                        }
                    ),
                )
            ]
        )

        with pytest.raises(
            TypeError,
            match="source_type must be a KnowledgeSourceType",
        ):
            resolver.supports(value)

    @pytest.mark.parametrize(
        "value",
        [
            "markdown",
            None,
            123,
        ],
    )
    def test_resolve_rejects_invalid_source_type(
        self,
        value,
    ) -> None:
        resolver = DefaultDocumentChunkerResolver(
            [
                StubChunker(
                    strategy_id="markdown",
                    supported_source_types=frozenset(
                        {
                            KnowledgeSourceType.MARKDOWN,
                        }
                    ),
                )
            ]
        )

        with pytest.raises(
            TypeError,
            match="source_type must be a KnowledgeSourceType",
        ):
            resolver.resolve(value)

    def test_resolve_unsupported_type_raises_typed_error(
        self,
    ) -> None:
        resolver = DefaultDocumentChunkerResolver(
            [
                StubChunker(
                    strategy_id="markdown",
                    supported_source_types=frozenset(
                        {
                            KnowledgeSourceType.MARKDOWN,
                        }
                    ),
                )
            ]
        )

        with pytest.raises(
            UnsupportedKnowledgeChunkingSourceTypeError
        ) as exc_info:
            resolver.resolve(
                KnowledgeSourceType.PDF
            )

        error = exc_info.value

        assert error.source_type == (
            KnowledgeSourceType.PDF
        )
        assert error.context["source_type"] == (
            KnowledgeSourceType.PDF.value
        )
        assert error.available_source_types == (
            KnowledgeSourceType.MARKDOWN.value,
        )


class TestResolverContractValidation:
    def test_non_chunker_object_rejected(
        self,
    ) -> None:
        class NotAChunker:
            pass

        with pytest.raises(
            KnowledgeChunkerConfigurationError,
            match="does not satisfy",
        ):
            DefaultDocumentChunkerResolver(
                [NotAChunker()]
            )

    def test_descriptor_must_be_chunker_descriptor(
        self,
    ) -> None:
        class BadDescriptorChunker:
            @property
            def descriptor(self):
                return "bad"

            @property
            def supported_source_types(self):
                return frozenset(
                    {
                        KnowledgeSourceType.MARKDOWN,
                    }
                )

            def supports(self, source_type):
                return True

            def chunk(self, document):
                raise NotImplementedError

        with pytest.raises(
            KnowledgeChunkerConfigurationError,
            match="descriptor must be a ChunkerDescriptor",
        ):
            DefaultDocumentChunkerResolver(
                [BadDescriptorChunker()]
            )

    def test_descriptor_access_failure_translated(
        self,
    ) -> None:
        class ExplodingDescriptorChunker:
            @property
            def descriptor(self):
                raise RuntimeError("boom")

            @property
            def supported_source_types(self):
                return frozenset(
                    {
                        KnowledgeSourceType.MARKDOWN,
                    }
                )

            def supports(self, source_type):
                return True

            def chunk(self, document):
                raise NotImplementedError

        with pytest.raises(
            KnowledgeChunkerConfigurationError,
            match="Unable to read document chunker descriptor",
        ) as exc_info:
            DefaultDocumentChunkerResolver(
                [ExplodingDescriptorChunker()]
            )

        assert isinstance(
            exc_info.value.__cause__,
            RuntimeError,
        )

    def test_supported_source_types_must_be_frozenset(
        self,
    ) -> None:
        class BadChunker:
            @property
            def descriptor(self):
                return ChunkerDescriptor(
                    strategy_id="bad",
                    version="1",
                )

            @property
            def supported_source_types(self):
                return {
                    KnowledgeSourceType.MARKDOWN
                }

            def supports(self, source_type):
                return True

            def chunk(self, document):
                raise NotImplementedError

        with pytest.raises(
            KnowledgeChunkerConfigurationError,
            match="must be a frozenset",
        ):
            DefaultDocumentChunkerResolver(
                [BadChunker()]
            )

    def test_supported_source_types_cannot_be_empty(
        self,
    ) -> None:
        chunker = StubChunker(
            strategy_id="empty",
            supported_source_types=frozenset(),
        )

        with pytest.raises(
            KnowledgeChunkerConfigurationError,
            match="must support at least one source type",
        ):
            DefaultDocumentChunkerResolver(
                [chunker]
            )

    def test_supported_source_types_must_contain_enums(
        self,
    ) -> None:
        class BadChunker:
            @property
            def descriptor(self):
                return ChunkerDescriptor(
                    strategy_id="bad",
                    version="1",
                )

            @property
            def supported_source_types(self):
                return frozenset({"markdown"})

            def supports(self, source_type):
                return True

            def chunk(self, document):
                raise NotImplementedError

        with pytest.raises(
            KnowledgeChunkerConfigurationError,
            match="contains values that are not",
        ):
            DefaultDocumentChunkerResolver(
                [BadChunker()]
            )

    def test_supported_source_types_access_failure_translated(
        self,
    ) -> None:
        class ExplodingChunker:
            @property
            def descriptor(self):
                return ChunkerDescriptor(
                    strategy_id="explode",
                    version="1",
                )

            @property
            def supported_source_types(self):
                raise RuntimeError("boom")

            def supports(self, source_type):
                return True

            def chunk(self, document):
                raise NotImplementedError

        with pytest.raises(
            KnowledgeChunkerConfigurationError,
            match="Unable to read document chunker supported",
        ) as exc_info:
            DefaultDocumentChunkerResolver(
                [ExplodingChunker()]
            )

        assert isinstance(
            exc_info.value.__cause__,
            RuntimeError,
        )

    def test_supports_must_return_boolean(
        self,
    ) -> None:
        class BadChunker(StubChunker):
            def supports(self, source_type):
                return "yes"

        chunker = BadChunker(
            strategy_id="bad",
            supported_source_types=frozenset(
                {
                    KnowledgeSourceType.MARKDOWN,
                }
            ),
        )

        with pytest.raises(
            KnowledgeChunkerConfigurationError,
            match="must return a boolean",
        ):
            DefaultDocumentChunkerResolver(
                [chunker]
            )

    def test_declared_support_must_match_supports_method(
        self,
    ) -> None:
        class LyingChunker(StubChunker):
            def supports(self, source_type):
                return False

        chunker = LyingChunker(
            strategy_id="liar",
            supported_source_types=frozenset(
                {
                    KnowledgeSourceType.MARKDOWN,
                }
            ),
        )

        with pytest.raises(
            KnowledgeChunkerConfigurationError,
            match="supports.*returns False",
        ):
            DefaultDocumentChunkerResolver(
                [chunker]
            )

    def test_supports_exception_is_translated(
        self,
    ) -> None:
        class ExplodingChunker(StubChunker):
            def supports(self, source_type):
                raise RuntimeError("boom")

        chunker = ExplodingChunker(
            strategy_id="explode",
            supported_source_types=frozenset(
                {
                    KnowledgeSourceType.MARKDOWN,
                }
            ),
        )

        with pytest.raises(
            KnowledgeChunkerConfigurationError,
            match="supports.*failed",
        ) as exc_info:
            DefaultDocumentChunkerResolver(
                [chunker]
            )

        assert isinstance(
            exc_info.value.__cause__,
            RuntimeError,
        )


class TestResolverImmutability:
    def test_mutating_original_input_collection_does_not_change_resolver(
        self,
    ) -> None:
        markdown = StubChunker(
            strategy_id="markdown",
            supported_source_types=frozenset(
                {
                    KnowledgeSourceType.MARKDOWN,
                }
            ),
        )

        chunkers = [markdown]

        resolver = DefaultDocumentChunkerResolver(
            chunkers
        )

        chunkers.clear()

        assert resolver.resolve(
            KnowledgeSourceType.MARKDOWN
        ) is markdown

    def test_resolver_has_no_runtime_registration_api(
        self,
    ) -> None:
        resolver = DefaultDocumentChunkerResolver(
            [
                StubChunker(
                    strategy_id="markdown",
                    supported_source_types=frozenset(
                        {
                            KnowledgeSourceType.MARKDOWN,
                        }
                    ),
                )
            ]
        )

        assert not hasattr(
            resolver,
            "register",
        )
        assert not hasattr(
            resolver,
            "unregister",
        )
        assert not hasattr(
            resolver,
            "replace",
        )