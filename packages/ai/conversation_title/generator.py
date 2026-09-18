# AI-customer-support-agent\packages\ai\conversation_title\generator.py
from __future__ import annotations
import logging

from packages.ai.conversation_title.fallback import ConversationTitleFallback
from packages.ai.conversation_title.models import ConversationTitleOutput, ConversationTitleResult, ConversationTitleSource
from packages.ai.conversation_title.prompts import ConversationTitlePromptBuilder
from packages.ai.conversation_title.sanitizer import ConversationTitleSanitizer
from packages.ai.providers.base import LLMProvider
from packages.ai.providers.errors import LLMProviderError

logger = logging.getLogger(__name__)

class ConversationTitleGenerator:
    """
    Generate a safe title from the first customer message.

    The provider is optional from the perspective of business success:
    provider failure, timeout, malformed output, or privacy rejection results in a deterministic fallback title.

    Programming/configuration errors are not silently converted into provider failures.
    For example, supplying an invalid provider implementation still raises during construction.
    """
    def __init__(self, *, provider: LLMProvider, prompt_builder: ConversationTitlePromptBuilder | None = None, 
                 sanitizer: ConversationTitleSanitizer | None = None, fallback: ConversationTitleFallback | None = None
    ) -> None:
        if not isinstance(provider, LLMProvider):
            raise TypeError("provider must implement LLMProvider")

        if prompt_builder is not None and not isinstance(prompt_builder, ConversationTitlePromptBuilder):
            raise TypeError("prompt_builder must be a ConversationTitlePromptBuilder or None")

        if sanitizer is not None and not isinstance(sanitizer, ConversationTitleSanitizer):
            raise TypeError("sanitizer must be a ConversationTitleSanitizer or None")

        if fallback is not None and not isinstance(fallback, ConversationTitleFallback):
            raise TypeError("fallback must be a ConversationTitleFallback or None")

        self._provider = provider
        self._prompt_builder = prompt_builder if prompt_builder is not None else ConversationTitlePromptBuilder()
        self._sanitizer = sanitizer if sanitizer is not None else ConversationTitleSanitizer()
        self._fallback = fallback if fallback is not None else ConversationTitleFallback()

    def generate(self, *, customer_message: str, intent: str | None = None) -> ConversationTitleResult:
        if not isinstance(customer_message, str):
            raise TypeError("customer_message must be a string")

        if intent is not None and not isinstance(intent, str):
            raise TypeError("intent must be a string or None")

        fallback_result = self._fallback.generate(customer_message=customer_message, intent=intent)
        # The start-message API already rejects blank input. This defensive# behavior keeps title generation non-critical if called elsewhere.
        if not customer_message.strip():
            self._record_fallback(reason="blank_input")
            return fallback_result

        prompt = self._prompt_builder.build(customer_message=customer_message)

        try:
            response = self._provider.generate_structured(
                system_prompt=prompt.system_prompt,
                user_prompt=prompt.user_prompt,
                response_model=ConversationTitleOutput,
            )
        except LLMProviderError:
            # Provider adapters already convert raw provider failures into safe provider-neutral errors. Do not log the exception text.
            self._record_fallback(reason="provider_failure")
            return fallback_result

        output = response.output
        if not isinstance(output, ConversationTitleOutput):
            # A provider returning the wrong validated model violates the
            # provider abstraction itself. Do not silently hide that defect.
            raise TypeError("provider returned an unexpected structured response model")

        sanitized_title = self._sanitizer.sanitize(output.title)
        if sanitized_title is None:
            self._record_fallback(reason="unsafe_or_invalid_output")
            return fallback_result

        return ConversationTitleResult(title=sanitized_title, source=ConversationTitleSource.PROVIDER)

    def _record_fallback(self, *, reason: str) -> None:
        """
        Emit only low-cardinality operational metadata.

        Customer text, prompts, provider responses, and exception messages must never be included here.
        """
        logger.info(
            "conversation_title_fallback_used",
            extra={
                "reason": reason,
                "provider": self._provider.provider_name,
                "model": self._provider.model_name,
            },
        )