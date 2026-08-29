import pytest

from packages.knowledge.ingestion.parser.base import (
    ParserDescriptor,
)


class TestParserDescriptor:
    def test_valid_descriptor(self):
        descriptor = ParserDescriptor(
            strategy_id="plain-text-structural",
            version="1.0.0",
            config_fingerprint="abc123",
        )

        assert (
            descriptor.strategy_id
            == "plain-text-structural"
        )
        assert descriptor.version == "1.0.0"
        assert descriptor.config_fingerprint == "abc123"

    def test_config_fingerprint_is_optional(self):
        descriptor = ParserDescriptor(
            strategy_id="plain-text-structural",
            version="1.0.0",
        )

        assert descriptor.config_fingerprint is None

    @pytest.mark.parametrize(
        "strategy_id",
        ["", " ", "\t", "\n"],
    )
    def test_blank_strategy_id_rejected(
        self,
        strategy_id,
    ):
        with pytest.raises(ValueError, match="strategy_id must not be blank"):
            ParserDescriptor(
                strategy_id=strategy_id,
                version="1.0.0",
            )

    @pytest.mark.parametrize(
        "version",
        ["", " ", "\t", "\n"],
    )
    def test_blank_version_rejected(
        self,
        version,
    ):
        with pytest.raises(ValueError):
            ParserDescriptor(
                strategy_id="plain-text-structural",
                version=version,
            )

    @pytest.mark.parametrize(
        "fingerprint",
        ["", " ", "\t", "\n"],
    )
    def test_blank_config_fingerprint_rejected(
        self,
        fingerprint,
    ):
        with pytest.raises(ValueError):
            ParserDescriptor(
                strategy_id="plain-text-structural",
                version="1.0.0",
                config_fingerprint=fingerprint,
            )

    def test_non_string_strategy_id_rejected(self):
        with pytest.raises(TypeError):
            ParserDescriptor(
                strategy_id=123,  # type: ignore[arg-type]
                version="1.0.0",
            )

    def test_non_string_version_rejected(self):
        with pytest.raises(TypeError):
            ParserDescriptor(
                strategy_id="plain-text-structural",
                version=123,  # type: ignore[arg-type]
            )

    def test_non_string_fingerprint_rejected(self):
        with pytest.raises(TypeError):
            ParserDescriptor(
                strategy_id="plain-text-structural",
                version="1.0.0",
                config_fingerprint=123,  # type: ignore[arg-type]
            )