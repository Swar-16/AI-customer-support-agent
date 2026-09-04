from __future__ import annotations
from collections import Counter

from packages.ai.generation.models import Citation, GroundedGenerationRequest, GroundedGenerationResult, GroundingStatus
from packages.ai.generation.prompts import GroundedGenerationPromptBuilder
from packages.ai.orchestration.state import RetrievedEvidence
from packages.ai.providers.base import LLMProvider
from packages.ai.providers.errors import LLMProviderError, LLMProviderResponseError, LLMProviderTimeoutError
from packages.ai.providers.types import StructuredLLMResponse

# Domain errors
class GroundedGenerationError(RuntimeError):
    """
    Base exception for grounded response-generation failures.

    Lower-level provider/transport failures are translated into this domain taxonomy so callers do not
    need to depend directly on provider-specific failure semantics.
    """

class InvalidGenerationInputError(GroundedGenerationError):
    """
    Raised when input violates generation-layer invariants before the provider is invoked.
    """

class GroundedGenerationTimeoutError(GroundedGenerationError):
    """Raised when the underlying LLM provider times out."""

class GroundedGenerationProviderError(GroundedGenerationError):
    """Raised when the provider fails for reasons other than a timeout or invalid structured response."""

class InvalidGroundedGenerationResponseError(GroundedGenerationError):
    """
    Raised when the model/provider response violates the semantic generation contract.

    Examples:
    - malformed structured wrapper;
    - wrong output model;
    - hallucinated citation source IDs;
    - duplicate citations;
    - grounded response without citations;
    - citations attached to a non-grounded response.
    """

# Generator
class GroundedResponseGenerator:
    """
    Produce customer-facing responses grounded in supplied evidence.

    Pipeline
    --------

        GroundedGenerationRequest
                  |
                  v
        GroundedGenerationPromptBuilder
                  |
                  v
             LLMProvider
        generate_structured(...)
                  |
                  v
        GroundedGenerationResult
                  |
                  v
        deterministic validation

    Responsibilities
    ----------------
    - render the trusted generation prompt;
    - invoke the provider through the provider-neutral interface;
    - require structured GroundedGenerationResult output;
    - translate provider failures into generation-domain failures;
    - verify citation provenance deterministically;
    - enforce cross-object grounding invariants.

    Those concerns belong to retrieval, decision, guardrail, application, resilience, and orchestration layers respectively.
    """
    def __init__(self, *, provider: LLMProvider, prompt_builder: GroundedGenerationPromptBuilder | None = None) -> None:
        if provider is None:
            raise TypeError("provider cannot be None")

        if prompt_builder is not None and not isinstance(prompt_builder, GroundedGenerationPromptBuilder):
            raise TypeError("prompt_builder must be a GroundedGenerationPromptBuilder instance or None")

        self._provider = provider
        self._prompt_builder = prompt_builder or GroundedGenerationPromptBuilder()

    def generate(self, *, request: GroundedGenerationRequest) -> GroundedGenerationResult:
        """
        Generate and return only the semantic customer-response result.

        Use `generate_with_response()` when provider metadata such as model, token usage, provider request ID, or estimated cost is also needed.
        """
        response = self.generate_with_response(request=request)
        return response.output

    def generate_with_response(self, *, request: GroundedGenerationRequest) -> StructuredLLMResponse[GroundedGenerationResult]:
        """
        Generate a grounded customer response and preserve provider metadata.

        Validation occurs in three phases:

        1. Request-domain validation before any provider call.
        2. Provider/schema validation at the provider boundary.
        3. Cross-object provenance validation after generation.

        The third phase is essential because a structurally valid LLM response may still hallucinate a 
        source ID or declare itself grounded without actually citing supplied evidence.
        """
        self._validate_request(request)
        prompt = self._prompt_builder.build(request=request)

        try:
            response = self._provider.generate_structured(
                system_prompt=prompt.system_prompt,
                user_prompt=prompt.user_prompt,
                response_model=GroundedGenerationResult,
            )

        except LLMProviderTimeoutError as exc:
            raise GroundedGenerationTimeoutError("Grounded response generation timed out.") from exc

        except LLMProviderResponseError as exc:
            raise InvalidGroundedGenerationResponseError("Generation provider returned an invalid structured response.") from exc

        except LLMProviderError as exc:
            raise GroundedGenerationProviderError("Grounded response generation provider failed.") from exc

        except Exception as exc:
            raise GroundedGenerationError("Unexpected grounded response generation failure.") from exc

        self._validate_provider_response(response)
        self._validate_semantics(request=request, result=response.output)

        return response

    # Request validation
    @staticmethod
    def _validate_request(request: GroundedGenerationRequest) -> None:
        """
        Validate invariants that cannot safely be left to type hints.

        GroundedGenerationRequest itself handles field-level Pydantic validation. This method protects 
        runtime boundaries from callers bypassing static typing or constructing malformed objects.
        """
        if not isinstance(request, GroundedGenerationRequest):
            raise InvalidGenerationInputError("request must be a GroundedGenerationRequest instance")

        GroundedResponseGenerator._validate_evidence_identity(request.evidence)

    @staticmethod
    def _validate_evidence_identity(evidence: tuple[RetrievedEvidence, ...]) -> None:
        """
        Ensure addressable evidence has unambiguous source identities.

        `source_id=None` is allowed because not every evidence source is necessarily citable.

        Duplicate non-null source IDs are rejected because a citation such as `source_id="abc"` would otherwise
        be ambiguous: there would be no deterministic way to know which evidence block it refers to.
        """
        source_ids = [item.source_id for item in evidence if item.source_id is not None]
        duplicate_ids = sorted(source_id for source_id, count in Counter(source_ids).items() if count > 1)
        if duplicate_ids:
            duplicates = ", ".join(repr(source_id) for source_id in duplicate_ids)
            raise InvalidGenerationInputError(f"evidence contains duplicate non-null source_id values: {duplicates}")


    # Provider response validation
    @staticmethod
    def _validate_provider_response(response: StructuredLLMResponse[GroundedGenerationResult]) -> None:
        """
        Defensively verify the provider-neutral response contract.

        LLMProvider implementations are expected to obey this contract, but custom adapters, 
        mocks, and future provider implementations should not be blindly trusted.
        """
        if not isinstance(response, StructuredLLMResponse):
            raise InvalidGroundedGenerationResponseError(f"Provider returned an unexpected response wrapper: {type(response).__name__}")

        if not isinstance(response.output, GroundedGenerationResult):
            raise InvalidGroundedGenerationResponseError(f"Provider returned an unexpected structured output: {type(response.output).__name__}")

    # Semantic / provenance validation
    @classmethod
    def _validate_semantics(cls, *, request: GroundedGenerationRequest, result: GroundedGenerationResult) -> None:
        """
        Enforce invariants involving both request evidence and model output.

        These rules deliberately live here rather than inside the Pydantic result model because 
        GroundedGenerationResult cannot know which evidence was supplied for the request that produced it.
        """
        cls._validate_grounding_status_contract(request=request, result=result)
        cls._validate_citations(request=request, citations=result.citations)

    @staticmethod
    def _validate_grounding_status_contract(*, request: GroundedGenerationRequest, result: GroundedGenerationResult) -> None:
        if result.grounding_status is GroundingStatus.GROUNDED:
            if not request.evidence:
                raise InvalidGroundedGenerationResponseError("A grounded response cannot be returned when no evidence was supplied.")

            if not result.citations:
                raise InvalidGroundedGenerationResponseError("A grounded response must cite at least one supplied evidence source.")

            return

        if result.grounding_status is GroundingStatus.INSUFFICIENT_EVIDENCE:
            if result.citations:
                raise InvalidGroundedGenerationResponseError("An insufficient-evidence response must not contain citations.")

            return

        if result.grounding_status is GroundingStatus.NOT_REQUIRED:
            if result.citations:
                raise InvalidGroundedGenerationResponseError("A not-required response must not contain citations.")

            return

        # GroundedGenerationResult currently prevents reaching this branch, but keeping this guard makes the 
        # business invariant explicit even if model construction is bypassed or the enum changes later.
        raise InvalidGroundedGenerationResponseError("Response contains an unsupported grounding status.")

    @classmethod
    def _validate_citations(cls, *, request: GroundedGenerationRequest, citations: tuple[Citation, ...]) -> None:
        if not citations:
            return

        evidence_by_source_id = {evidence.source_id: evidence for evidence in request.evidence if evidence.source_id is not None}
        seen_source_ids: set[str] = set()
        for citation in citations:
            source_id = citation.source_id
            if source_id in seen_source_ids:
                raise InvalidGroundedGenerationResponseError(f"Response contains duplicate citation source_id: {source_id!r}")

            seen_source_ids.add(source_id)
            evidence = evidence_by_source_id.get(source_id)
            if evidence is None:
                raise InvalidGroundedGenerationResponseError(f"Response cited a source that was not supplied as evidence: {source_id!r}")

            cls._validate_citation_identity(citation=citation, evidence=evidence)

    @staticmethod
    def _validate_citation_identity(*, citation: Citation, evidence: RetrievedEvidence) -> None:
        """
        Prevent the model from fabricating human-readable source identity.

        title/section are optional in Citation. If omitted, that is valid.

        If the model chooses to provide either value, however, it must exactly match the corresponding supplied
        evidence field. The model is not allowed to invent a more convincing document title or section label.
        """
        if citation.title is not None and citation.title != evidence.title:
            raise InvalidGroundedGenerationResponseError(f"Citation title does not match the supplied evidence for source_id {citation.source_id!r}.")

        if citation.section is not None and citation.section != evidence.section:
            raise InvalidGroundedGenerationResponseError(f"Citation section does not match the supplied evidence for source_id {citation.source_id!r}.")