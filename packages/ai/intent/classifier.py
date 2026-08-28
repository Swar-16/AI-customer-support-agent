from __future__ import annotations
from dataclasses import dataclass
from typing import Final

from packages.ai.intent.schemas import IntentResult
from packages.ai.intent.taxonomy import INTENT_DEFINITIONS, IntentType
from packages.ai.providers.base import LLMProvider
from packages.ai.providers.errors import LLMProviderError, LLMProviderResponseError, LLMProviderTimeoutError
from packages.ai.providers.types import StructuredLLMResponse


DEFAULT_MAX_MESSAGE_LENGTH: Final[int] = 20_000


class IntentClassificationError(RuntimeError):
    """
    Base exception for failures occurring during intent classification.

    The classifier converts lower-level provider failures into domain-level
    classification errors so callers do not need to understand vendor or
    transport-specific exceptions.
    """


class InvalidIntentInputError(IntentClassificationError):
    """Raised when classification input is invalid before reaching the LLM."""


class IntentClassificationTimeoutError(IntentClassificationError):
    """Raised when the underlying provider times out."""


class IntentClassificationProviderError(IntentClassificationError):
    """Raised when the provider cannot successfully complete the request."""


class InvalidIntentResponseError(IntentClassificationError):
    """
    Raised when the provider returns a response that cannot satisfy the
    IntentResult contract.
    """


@dataclass(frozen=True, slots=True)
class IntentClassifierConfig:
    """
    Runtime configuration for intent classification.

    Configuration is intentionally small. Model/provider selection,
    retries, circuit breakers, persistence, and telemetry belong outside
    this classifier.
    """

    max_message_length: int = DEFAULT_MAX_MESSAGE_LENGTH

    include_examples_in_prompt: bool = True

    max_examples_per_intent: int = 2

    def __post_init__(self) -> None:
        if self.max_message_length <= 0:
            raise ValueError(
                "max_message_length must be greater than zero"
            )

        if self.max_examples_per_intent < 0:
            raise ValueError(
                "max_examples_per_intent cannot be negative"
            )


class IntentClassifier:
    """
    Classifies a customer message into the canonical intent taxonomy.

    Responsibilities:
        - validate classification input
        - construct taxonomy-aware classification instructions
        - invoke the configured LLM provider
        - require structured IntentResult output
        - translate provider failures into classifier-level failures

    Explicitly NOT responsible for:
        - database persistence
        - retries/backoff
        - telemetry persistence
        - retrieval / RAG
        - business authorization
        - action execution
        - escalation policy
        - conversation storage

    These boundaries keep classification independently testable and prevent
    infrastructure concerns from leaking into the AI-domain component.
    """

    def __init__(self, *, provider: LLMProvider, config: IntentClassifierConfig | None = None) -> None:
        if provider is None:
            raise TypeError("provider cannot be None")

        self._provider = provider
        self._config = config or IntentClassifierConfig()

    def classify_with_response(self, *, customer_message: str, conversation_context: str | None = None,) -> StructuredLLMResponse[IntentResult]:
        """
        Classify one customer message and return the complete normalized
        provider response.

        This method is intended for application/orchestration infrastructure
        that needs both:   IntentResult + provider telemetry

        including:
            - provider/model identity
            - token usage
            - provider request ID
            - estimated cost

        Raises:
            InvalidIntentInputError:
                Input is empty, malformed, or exceeds configured limits.

            IntentClassificationTimeoutError:
                Provider invocation timed out.

            InvalidIntentResponseError:
                Provider returned output incompatible with IntentResult.

            IntentClassificationProviderError:
                Other provider failure occurred.
        """

        normalized_message = self._validate_and_normalize_message(customer_message)
        normalized_context = self._normalize_context(conversation_context)
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(customer_message=normalized_message, conversation_context=normalized_context)

        try:
            response = self._provider.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=IntentResult,
            )

        except LLMProviderTimeoutError as exc:
            raise IntentClassificationTimeoutError("Intent classification timed out.") from exc

        except LLMProviderResponseError as exc:
            raise InvalidIntentResponseError("Intent provider returned an invalid structured response.") from exc

        except LLMProviderError as exc:
            raise IntentClassificationProviderError("Intent classification provider failed.") from exc

        except Exception as exc:
            raise IntentClassificationError("Unexpected intent classification failure.") from exc

        self._validate_provider_response(response)

        return response
    
    @staticmethod
    def _validate_provider_response(response: StructuredLLMResponse[IntentResult]) -> None:
        """
        Defensively verify the provider contract.

        Concrete providers are expected to obey LLMProvider, but this boundary
        protects the classifier from malformed third-party/custom adapters.
        """
        if not isinstance(response, StructuredLLMResponse):
            raise InvalidIntentResponseError(f"Provider returned an unexpected response wrapper: {type(response).__name__}")

        if not isinstance(response.output, IntentResult):
            raise InvalidIntentResponseError(f"Provider returned an unexpected structured output: {type(response.output).__name__}")

    def classify(self, *, customer_message: str, conversation_context: str | None = None) -> IntentResult:
        """
        Classify one customer message and return only the semantic result.

        Use `classify_with_response()` when provider metadata such as token
        usage, model identity, request ID, or estimated cost is also required.
        """
        response = self.classify_with_response(
            customer_message=customer_message,
            conversation_context=conversation_context,
        )

        return response.output

    def _validate_and_normalize_message(self, customer_message: str) -> str:
        if not isinstance(customer_message, str):
            raise InvalidIntentInputError("customer_message must be a string")

        normalized = customer_message.strip()
        if not normalized:
            raise InvalidIntentInputError("customer_message cannot be empty")

        if len(normalized) > self._config.max_message_length:
            raise InvalidIntentInputError(f"customer_message exceeds maximum supported length of {self._config.max_message_length} characters")

        return normalized

    @staticmethod
    def _normalize_context(conversation_context: str | None) -> str | None:
        if conversation_context is None:
            return None

        if not isinstance(conversation_context, str):
            raise InvalidIntentInputError("conversation_context must be a string or None")

        normalized = conversation_context.strip()

        return normalized or None

    def _build_system_prompt(self) -> str:
        """
        Build classification instructions from the canonical taxonomy.

        For the first implementation this is generated in code. Once the
        prompt registry/versioning layer is wired in, this method should be
        replaced by a PromptRepository/PromptRegistry dependency while the
        classifier contract remains unchanged.
        """

        taxonomy_text = self._render_taxonomy()

        return (
            "You are an intent classification component inside a customer "
            "support system.\n\n"

            "Your sole responsibility is to classify the customer's latest "
            "message into exactly one canonical intent and extract only "
            "information explicitly supported by the message or supplied "
            "conversation context.\n\n"

            "Do not answer the customer.\n"
            "Do not recommend or execute business actions.\n"
            "Do not invent identifiers, facts, policies, or entities.\n"
            "Do not infer an order ID, transaction ID, subscription ID, or "
            "account ID unless it is explicitly present.\n"
            "When classification is genuinely uncertain, use the UNKNOWN "
            "intent and set needs_clarification=true.\n"
            "When the intent is clear but required operational information "
            "is missing, preserve the correct intent and set "
            "needs_clarification=true.\n\n"

            "The confidence field is a classification confidence signal "
            "between 0 and 1. Avoid artificial certainty for ambiguous "
            "messages.\n\n"

            "reason_summary must contain only a short audit-friendly "
            "explanation of the classification. Do not provide hidden "
            "reasoning or step-by-step chain-of-thought.\n\n"

            "Canonical taxonomy:\n"
            f"{taxonomy_text}"
        )

    def _build_user_prompt(self, *, customer_message: str, conversation_context: str | None) -> str:
        """
        Keep customer-controlled content explicitly delimited.

        Delimiting user input does not by itself solve prompt injection, but
        it makes the trust boundary clear and improves prompt consistency.
        """

        if conversation_context is None:
            context_section = "No conversation context provided."
        else:
            context_section = (
                "<conversation_context>\n"
                f"{conversation_context}\n"
                "</conversation_context>"
            )

        return (
            f"{context_section}\n\n"
            "<customer_message>\n"
            f"{customer_message}\n"
            "</customer_message>\n\n"
            "Classify the customer_message according to the canonical "
            "taxonomy and return the required structured result."
        )

    def _render_taxonomy(self) -> str:
        sections: list[str] = []

        for intent in IntentType:
            definition = INTENT_DEFINITIONS[intent]

            section_parts = [
                f"- {intent.value}",
                f"  Description: {definition.description}",
            ]

            if self._config.include_examples_in_prompt:
                examples = definition.positive_examples[
                    : self._config.max_examples_per_intent
                ]

                if examples:
                    formatted_examples = "; ".join(
                        repr(example) for example in examples
                    )

                    section_parts.append(
                        f"  Examples: {formatted_examples}"
                    )

            sections.append("\n".join(section_parts))

        return "\n".join(sections)