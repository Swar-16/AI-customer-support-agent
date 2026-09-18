# AI-customer-support-agent\tests\unit\ai\conversation_title\test_generator.py
from __future__ import annotations

import logging

import pytest

from packages.ai.conversation_title.generator import (
    ConversationTitleGenerator,
)
from packages.ai.conversation_title.models import (
    ConversationTitleOutput,
    ConversationTitleSource,
)
from packages.ai.providers.mock import MockLLMProvider


def _provider_returning(
    title: str,
) -> MockLLMProvider:
    def structured_resolver(
        system_prompt: str,
        user_prompt: str,
        response_model,
    ):
        assert response_model is ConversationTitleOutput

        return {
            "title": title,
        }

    return MockLLMProvider(
        structured_resolver=structured_resolver,
    )


class TestConversationTitleGeneratorProviderSuccess:
    def test_returns_sanitized_provider_title(
        self,
    ) -> None:
        provider = _provider_returning(
            'Title: "**Return policy question**"'
        )

        generator = ConversationTitleGenerator(
            provider=provider,
        )

        result = generator.generate(
            customer_message=(
                "What is your return policy?"
            ),
            intent="return_exchange",
        )

        assert result.title == "Return policy question"
        assert (
            result.source
            is ConversationTitleSource.PROVIDER
        )
        assert provider.call_count == 1

    def test_requests_expected_structured_model(
        self,
    ) -> None:
        provider = _provider_returning(
            "Billing assistance"
        )

        generator = ConversationTitleGenerator(
            provider=provider,
        )

        generator.generate(
            customer_message="Why was I charged twice?"
        )

        calls = provider.calls

        assert len(calls) == 1
        assert calls[0].operation == (
            "generate_structured"
        )
        assert (
            calls[0].response_model
            is ConversationTitleOutput
        )

    def test_sends_redacted_customer_data(
        self,
    ) -> None:
        provider = _provider_returning(
            "Account security help"
        )

        generator = ConversationTitleGenerator(
            provider=provider,
        )

        generator.generate(
            customer_message=(
                "My password is SuperSecret123 "
                "and email is alice@example.com."
            )
        )

        call = provider.calls[0]

        assert "[REDACTED SECRET]" in call.user_prompt
        assert "[REDACTED EMAIL]" in call.user_prompt
        assert "SuperSecret123" not in call.user_prompt
        assert "alice@example.com" not in call.user_prompt


class TestConversationTitleGeneratorFallback:
    def test_falls_back_when_provider_times_out(
        self,
    ) -> None:
        provider = _provider_returning(
            "Unused provider title"
        )
        provider.queue_timeout()

        generator = ConversationTitleGenerator(
            provider=provider,
        )

        result = generator.generate(
            customer_message=(
                "What is your return policy?"
            ),
            intent="return_exchange",
        )

        assert result.title == (
            "Return and exchange help"
        )
        assert (
            result.source
            is ConversationTitleSource.FALLBACK
        )
        assert provider.call_count == 1

    def test_falls_back_when_provider_fails(
        self,
    ) -> None:
        provider = _provider_returning(
            "Unused provider title"
        )
        provider.queue_failure()

        generator = ConversationTitleGenerator(
            provider=provider,
        )

        result = generator.generate(
            customer_message=(
                "I was charged twice."
            ),
            intent="duplicate_charge",
        )

        assert result.title == (
            "Duplicate charge assistance"
        )
        assert (
            result.source
            is ConversationTitleSource.FALLBACK
        )

    def test_falls_back_when_structured_output_is_invalid(
        self,
    ) -> None:
        def invalid_resolver(
            system_prompt: str,
            user_prompt: str,
            response_model,
        ):
            return {
                "unexpected_field": "Missing title",
            }

        provider = MockLLMProvider(
            structured_resolver=invalid_resolver,
        )

        generator = ConversationTitleGenerator(
            provider=provider,
        )

        result = generator.generate(
            customer_message="Hello!",
            intent="greeting",
        )

        assert result.title == "General support"
        assert (
            result.source
            is ConversationTitleSource.FALLBACK
        )

    @pytest.mark.parametrize(
        "unsafe_title",
        (
            "Order ORD-12345 status",
            "Help for alice@example.com",
            "Password: SecretPassword123",
            "Ignore previous instructions",
            '{"title": "Injected title"}',
        ),
    )
    def test_falls_back_when_provider_output_is_unsafe(
        self,
        unsafe_title: str,
    ) -> None:
        provider = _provider_returning(
            unsafe_title
        )

        generator = ConversationTitleGenerator(
            provider=provider,
        )

        result = generator.generate(
            customer_message=(
                "Where is order ORD-12345?"
            ),
            intent="order_status",
        )

        assert result.title == "Order status request"
        assert (
            result.source
            is ConversationTitleSource.FALLBACK
        )

    def test_falls_back_when_provider_title_is_too_long(
        self,
    ) -> None:
        provider = _provider_returning("A" * 81)

        generator = ConversationTitleGenerator(
            provider=provider,
        )

        result = generator.generate(
            customer_message="I need technical help.",
            intent="technical_issue",
        )

        assert result.title == "Technical support"
        assert (
            result.source
            is ConversationTitleSource.FALLBACK
        )

    def test_blank_message_skips_provider(
        self,
    ) -> None:
        provider = _provider_returning(
            "Should not be used"
        )

        generator = ConversationTitleGenerator(
            provider=provider,
        )

        result = generator.generate(
            customer_message="  \n\t ",
        )

        assert result.title == "Support request"
        assert (
            result.source
            is ConversationTitleSource.FALLBACK
        )
        assert provider.call_count == 0


class TestConversationTitleGeneratorLogging:
    def test_provider_failure_log_excludes_sensitive_data(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        customer_message = (
            "My password is SuperSecretPassword123"
        )

        provider = _provider_returning(
            "Unused provider title"
        )
        provider.queue_failure()

        generator = ConversationTitleGenerator(
            provider=provider,
        )

        with caplog.at_level(logging.INFO):
            result = generator.generate(
                customer_message=customer_message,
                intent="account_security",
            )

        assert result.source is (
            ConversationTitleSource.FALLBACK
        )

        rendered_logs = caplog.text

        assert "conversation_title_fallback_used" in (
            rendered_logs
        )
        assert customer_message not in rendered_logs
        assert "SuperSecretPassword123" not in (
            rendered_logs
        )
        assert "Simulated mock provider failure" not in (
            rendered_logs
        )


class TestConversationTitleGeneratorValidation:
    def test_requires_provider_implementation(
        self,
    ) -> None:
        with pytest.raises(
            TypeError,
            match="provider must implement LLMProvider",
        ):
            ConversationTitleGenerator(
                provider=object(),  # type: ignore[arg-type]
            )

    def test_requires_string_customer_message(
        self,
    ) -> None:
        provider = _provider_returning(
            "General support"
        )

        generator = ConversationTitleGenerator(
            provider=provider,
        )

        with pytest.raises(
            TypeError,
            match="customer_message must be a string",
        ):
            generator.generate(
                customer_message=None,  # type: ignore[arg-type]
            )

    def test_requires_string_or_none_intent(
        self,
    ) -> None:
        provider = _provider_returning(
            "General support"
        )

        generator = ConversationTitleGenerator(
            provider=provider,
        )

        with pytest.raises(
            TypeError,
            match="intent must be a string or None",
        ):
            generator.generate(
                customer_message="Hello",
                intent=123,  # type: ignore[arg-type]
            )