# AI-customer-support-agent\packages\application\ai\answer_service.py
from __future__ import annotations
from dataclasses import dataclass

from packages.ai.decision.policies import RetrievalKind
from packages.ai.decision.schemas import DecisionResult, DecisionType
from packages.ai.generation.generator import GroundedResponseGenerator
from packages.ai.generation.models import GroundedGenerationRequest, GroundedGenerationResult
from packages.ai.intent.schemas import IntentResult
from packages.ai.orchestration.state import RetrievedEvidence
from packages.application.knowledge.evidence_mapper import KnowledgeEvidenceMapper
from packages.application.knowledge.retrieval_context_service import KnowledgeRetrievalContextService
from packages.knowledge.retrieval.application.build_grounding_context import BuildGroundingContext
from packages.knowledge.retrieval.models import RetrievalFilters
from packages.knowledge.retrieval.query.service import RetrievalQueryPreparationService


# Application errors
class AnswerServiceError(RuntimeError):
    """
    Base application-layer failure for answer orchestration.

    Retrieval-domain failures and generation-domain failures deliberately remain their own typed exceptions
    and are not collapsed into this base class. Higher-level orchestration can therefore distinguish:

        retrieval failure
        generation failure
        unsupported routing
        malformed application input
    """

class InvalidAnswerRequestError(AnswerServiceError):
    """Raised when the caller supplies an invalid answer-service request."""

class UnsupportedAnswerDecisionError(AnswerServiceError):
    """Raised when the service is asked to execute a decision that does not belong to its current responsibility."""

class UnsupportedRetrievalKindError(AnswerServiceError):
    """
    Raised when a valid retrieval decision targets a source category that this service cannot execute yet.

    V1 intentionally implements KNOWLEDGE retrieval only.

    OPERATIONAL retrieval will later be handled by operational tools/services that produce the same neutral RetrievedEvidence contract.
    """

class InvalidRetrievalDecisionError(AnswerServiceError):
    """Raised when a RETRIEVE_INFORMATION decision does not contain a valid, recognizable retrieval-kind contract."""

# Request / result contracts
@dataclass(frozen=True, slots=True)
class AnswerServiceRequest:
    """
    Immutable application-level input for one grounded-answer operation.

    This request represents already-understood and already-routed customer input.
    Intent classification and decision making must happen before this service is called.

    Trust model
    -----------
    customer_message:
        untrusted customer-authored text.

    intent_result:
        semantic AI output already validated against IntentResult.

    decision_result:
        deterministic routing decision produced by DecisionEngine.

    trusted_filters:
        application-controlled retrieval constraints.

    conversation_context:
        optional bounded prior conversation context selected by the caller.
    """
    customer_message: str
    intent_result: IntentResult
    decision_result: DecisionResult
    trusted_filters: RetrievalFilters | None = None
    conversation_context: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.customer_message, str):
            raise TypeError("customer_message must be a string")

        normalized_message = self.customer_message.strip()
        if not normalized_message:
            raise ValueError("customer_message cannot be empty")

        object.__setattr__(self, "customer_message", normalized_message)
        if not isinstance(self.intent_result, IntentResult):
            raise TypeError("intent_result must be an IntentResult instance")

        if not isinstance(self.decision_result, DecisionResult):
            raise TypeError("decision_result must be a DecisionResult instance")

        if self.trusted_filters is not None and not isinstance(self.trusted_filters, RetrievalFilters):
            raise TypeError("trusted_filters must be a RetrievalFilters instance or None")

        if self.conversation_context is not None:
            if not isinstance(self.conversation_context, str):
                raise TypeError("conversation_context must be a string or None")

            normalized_context = self.conversation_context.strip()
            object.__setattr__(self, "conversation_context", normalized_context or None)

@dataclass(frozen=True, slots=True)
class AnswerServiceResult:
    """
    Result of one successful answer operation.

    Evidence and generation are intentionally returned separately.

    The orchestrator owns AIState transitions and can therefore apply:

        state.with_retrieved_evidence(result.evidence)
        state.with_generated_response(result.generation.answer)

    without this application service knowing about AIState lifecycle rules.
    """
    evidence: tuple[RetrievedEvidence, ...]
    generation: GroundedGenerationResult

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, tuple):
            raise TypeError("evidence must be a tuple")

        if not all(isinstance(item, RetrievedEvidence) for item in self.evidence):
            raise TypeError("all evidence items must be RetrievedEvidence instances")

        if not isinstance(self.generation, GroundedGenerationResult):
            raise TypeError("generation must be a GroundedGenerationResult instance")

# Service
class AnswerService:
    """
    Application-layer integration service for grounded customer answers.

    V1 flow
    -------

        AnswerServiceRequest
                |
                v
        validate routing decision
                |
                v
        KNOWLEDGE retrieval
                |
                v
        KnowledgeRetrievalContextService
                |
                v
        RetrievalQueryContext
                |
                v
        RetrievalQueryPreparationService
                |
                v
        PreparedRetrievalQuery
                |
                v
        BuildGroundingContext
                |
                v
        GroundingContext
                |
                v
        KnowledgeEvidenceMapper
                |
                v
        tuple[RetrievedEvidence, ...]
                |
                v
        GroundedResponseGenerator
                |
                v
        GroundedGenerationResult

    Architectural responsibility
    ----------------------------
    This service connects the generic AI layer to the knowledge subsystem.

    The AI package therefore does NOT need to know about:
        - retrieval query preparation;
        - GroundingContext;
        - chunks;
        - vector retrieval;
        - lexical retrieval;
        - RRF;
        - embedding providers;
        - knowledge document versions.

    Likewise, the knowledge package does NOT depend on:
        - AIState;
        - DecisionResult;
        - GroundedGenerationResult;
        - LLM providers.

    Retrieval and generation failures intentionally propagate in their own domain-specific exception types so
    the orchestrator can classify them accurately.
    """
    def __init__(self, *, retrieval_context_service: KnowledgeRetrievalContextService, 
                 query_preparation_service: RetrievalQueryPreparationService, build_grounding_context: BuildGroundingContext,
                 evidence_mapper: KnowledgeEvidenceMapper, response_generator: GroundedResponseGenerator) -> None:
        if not isinstance(retrieval_context_service, KnowledgeRetrievalContextService):
            raise TypeError("retrieval_context_service must be a KnowledgeRetrievalContextService instance")

        if not isinstance(query_preparation_service, RetrievalQueryPreparationService):
            raise TypeError("query_preparation_service must be a RetrievalQueryPreparationService instance")

        if not isinstance(build_grounding_context, BuildGroundingContext):
            raise TypeError("build_grounding_context must be a BuildGroundingContext instance")

        if not isinstance(evidence_mapper, KnowledgeEvidenceMapper):
            raise TypeError("evidence_mapper must be a KnowledgeEvidenceMapper instance")

        if not isinstance(response_generator, GroundedResponseGenerator):
            raise TypeError("response_generator must be a GroundedResponseGenerator instance")

        self._retrieval_context_service = retrieval_context_service
        self._query_preparation_service = query_preparation_service
        self._build_grounding_context = build_grounding_context
        self._evidence_mapper = evidence_mapper
        self._response_generator = response_generator

    # Public API
    def answer(self, *, request: AnswerServiceRequest) -> AnswerServiceResult:
        """
        Execute one grounded-answer operation.

        Current V1 contract:
            only RETRIEVE_INFORMATION / KNOWLEDGE is supported.

        Other workflow decisions are rejected explicitly rather than silently converted into knowledge retrieval.

        This prevents routing bugs from accidentally causing the wrong source of truth to be queried.
        """
        if not isinstance(request, AnswerServiceRequest):
            raise InvalidAnswerRequestError("request must be an AnswerServiceRequest instance")

        retrieval_kind = self._resolve_retrieval_kind(request.decision_result)
        if retrieval_kind is RetrievalKind.OPERATIONAL:
            raise UnsupportedRetrievalKindError("Operational retrieval is not implemented by AnswerService V1.")

        if retrieval_kind is not RetrievalKind.KNOWLEDGE:
            # Defensive future-proofing if RetrievalKind gains another member.
            raise UnsupportedRetrievalKindError(f"Unsupported retrieval kind: {retrieval_kind.value!r}")

        return self._answer_from_knowledge(request=request)

    # Knowledge path
    def _answer_from_knowledge(self, *, request: AnswerServiceRequest) -> AnswerServiceResult:
        """
        Execute the complete knowledge-backed answer path.

        Empty retrieval is deliberately NOT treated as an exception.

        BuildGroundingContext already defines empty retrieval as a valid semantic outcome. The generator receives an
        empty evidence tuple and may respond with INSUFFICIENT_EVIDENCE instead of hallucinating.
        """
        retrieval_context = self._retrieval_context_service.create(
            customer_message=request.customer_message,
            intent_result=request.intent_result,
            trusted_filters=request.trusted_filters,
            conversation_context=request.conversation_context,
        )

        prepared_query = self._query_preparation_service.prepare(context=retrieval_context)
        grounding_context = self._build_grounding_context.build(prepared_query=prepared_query)
        evidence = self._evidence_mapper.map(context=grounding_context)
        generation_request = GroundedGenerationRequest(
            customer_message=request.customer_message,
            intent=request.intent_result,
            evidence=evidence,
            conversation_context=request.conversation_context,
        )
        generation = self._response_generator.generate(request=generation_request)
        
        return AnswerServiceResult(evidence=evidence, generation=generation)

    # Routing validation
    @staticmethod
    def _resolve_retrieval_kind(decision: DecisionResult) -> RetrievalKind:
        """
        Resolve and validate retrieval routing metadata.

        DecisionEngine currently persists retrieval_kind in DecisionResult.metadata rather than as a first-class field.

        We therefore validate that boundary here instead of blindly trusting arbitrary metadata strings.

        A future DecisionResult schema may promote retrieval_kind to a typed field; this method then becomes the single migration point.
        """
        if decision.decision is not DecisionType.RETRIEVE_INFORMATION:
            raise UnsupportedAnswerDecisionError(f"AnswerService V1 requires a RETRIEVE_INFORMATION decision; received {decision.decision.value!r}.")

        raw_kind = decision.metadata.get("retrieval_kind")
        if not isinstance(raw_kind, str):
            raise InvalidRetrievalDecisionError("RETRIEVE_INFORMATION decision must contain a string retrieval_kind in metadata.")

        normalized_kind = raw_kind.strip()
        if not normalized_kind:
            raise InvalidRetrievalDecisionError("retrieval_kind cannot be empty.")

        try:
            return RetrievalKind(normalized_kind)

        except ValueError as exc:
            raise InvalidRetrievalDecisionError(f"Unknown retrieval_kind: {normalized_kind!r}.") from exc