# AI-customer-support-agent\packages\application\composition\ai_pipeline_factory.py
from __future__ import annotations
import uuid
from dataclasses import dataclass
from decimal import Decimal
from collections.abc import Callable

from packages.ai.decision.engine import DecisionEngine, DecisionEngineConfig
from packages.ai.generation.generator import GroundedResponseGenerator
from packages.ai.generation.prompts import GroundedGenerationPromptBuilder
from packages.ai.intent.classifier import IntentClassifier, IntentClassifierConfig
from packages.ai.orchestration.orchestrator import AIOrchestrator, AIOrchestratorConfig, OrchestrationObserver
from packages.ai.providers.base import LLMProvider
from packages.ai.providers.instrumented import InstrumentedLLMProvider, LLMCallContext
from packages.ai.telemetry.recorder import TelemetryRecorder
from packages.database.repositories.ai.decision_repository import AIDecisionRepository
from packages.database.repositories.ai.intent_prediction_repository import IntentPredictionRepository
from packages.database.repositories.ai.llm_call_repository import LLMCallRepository
from packages.application.ai.answer_service import AnswerService
from packages.guardrails.evaluator import GuardrailEvaluator


AnswerServiceBuilder = Callable[[GroundedResponseGenerator], AnswerService]

# Immutable request-scoped pipeline bundle
@dataclass(frozen=True, slots=True)
class AIPipeline:
    """
    Fully composed AI component graph for one logical AI run.

    The pipeline owns no database transaction.

    Repository dependencies supplied to AIPipelineFactory are expected to belong to the caller's active UnitOfWork.

    One AI run may execute multiple LLM operations:

        intent classification
        response generation
        future query rewriting
        guardrail validation
        future conversation summarization

    Each operation therefore receives its own InstrumentedLLMProvider with an immutable LLMCallContext while all wrappers share:

        - the same base provider;
        - the same ai_run_id;
        - the same TelemetryRecorder.

    This prevents telemetry from being attributed to the wrong logical operation while keeping the expensive underlying provider reusable.
    """
    orchestrator: AIOrchestrator
    intent_classifier: IntentClassifier
    decision_engine: DecisionEngine
    grounded_response_generator: GroundedResponseGenerator
    guardrail_evaluator: GuardrailEvaluator
    intent_provider: InstrumentedLLMProvider
    generation_provider: InstrumentedLLMProvider
    telemetry_recorder: TelemetryRecorder

    @property
    def instrumented_provider(self) -> InstrumentedLLMProvider:
        """
        Temporary compatibility alias for the intent-classification provider.

        Older application code treated an AI pipeline as having one LLM provider because intent
        classification was originally the only provider-backed stage.

        New code MUST use the purpose-specific provider fields:

            intent_provider
            generation_provider

        This alias should be removed once ProcessCustomerMessage and any older tests no longer depend on it.
        """
        return self.intent_provider

# Repository dependencies
@dataclass(frozen=True, slots=True)
class AITelemetryRepositories:
    """
    Repository dependencies required by AI telemetry persistence.

    The composition layer depends on this narrow bundle rather than on the concrete SqlAlchemyUnitOfWork itself.

    All repositories supplied here must belong to the same active UnitOfWork and therefore the same transaction/session.
    """
    llm_calls: LLMCallRepository
    intent_predictions: IntentPredictionRepository
    ai_decisions: AIDecisionRepository

    def __post_init__(self) -> None:
        if not isinstance(self.llm_calls, LLMCallRepository):
            raise TypeError("llm_calls must be an LLMCallRepository")

        if not isinstance(self.intent_predictions, IntentPredictionRepository):
            raise TypeError("intent_predictions must be an IntentPredictionRepository")

        if not isinstance(self.ai_decisions, AIDecisionRepository):
            raise TypeError("ai_decisions must be an AIDecisionRepository")

# Factory configuration
@dataclass(frozen=True, slots=True)
class AIPipelineFactoryConfig:
    """
    Composition-level configuration for provider-backed AI operations.

    This configuration describes how LLM calls are attributed in telemetry.
    Component-specific behavioral configuration remains inside the individual component configuration objects.

    `*_prompt_version_id` refers to the persistent prompt-registry identifier, not the 
    human-readable prompt version string embedded in prompt code.

    `*_temperature` is currently telemetry/context metadata because the existing LLMProvider interface does not expose 
    per-call sampling options. It must not be interpreted as overriding the underlying provider's runtime temperature.
    """
    intent_purpose: str = "intent_classification"
    intent_temperature: Decimal | None = None
    intent_prompt_version_id: uuid.UUID | None = None
    generation_purpose: str = "answer_generation"
    generation_temperature: Decimal | None = None
    generation_prompt_version_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        self._normalize_purpose(field_name="intent_purpose", value=self.intent_purpose)
        self._normalize_purpose(field_name="generation_purpose", value=self.generation_purpose)
        self._validate_prompt_version_id(field_name="intent_prompt_version_id", value=self.intent_prompt_version_id)
        self._validate_prompt_version_id(field_name="generation_prompt_version_id", value=self.generation_prompt_version_id)
        self._validate_temperature(field_name="intent_temperature", value=self.intent_temperature)
        self._validate_temperature(field_name="generation_temperature", value=self.generation_temperature)

        if self.intent_purpose == self.generation_purpose:
            raise ValueError("intent_purpose and generation_purpose must be distinct")

    def _normalize_purpose(self, *, field_name: str, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be empty")

        object.__setattr__(self, field_name, normalized)

    @staticmethod
    def _validate_prompt_version_id(*, field_name: str, value: uuid.UUID | None) -> None:
        if value is not None and not isinstance(value, uuid.UUID):
            raise TypeError(f"{field_name} must be UUID or None")

    @staticmethod
    def _validate_temperature(*, field_name: str, value: Decimal | None) -> None:
        if value is None:
            return

        if not isinstance(value, Decimal):
            raise TypeError(f"{field_name} must be Decimal or None")

        if not Decimal("0") <= value <= Decimal("2"):
            raise ValueError(f"{field_name} must be between 0 and 2")

# Factory
class AIPipelineFactory:
    """
    Build the AI component graph for one AI run.

    Long-lived dependencies
    -----------------------
    - base LLM provider;
    - classifier configuration;
    - decision-engine configuration;
    - orchestrator configuration;
    - generation prompt builder;
    - optional orchestration observer;
    - composition configuration.
    - guardrail evaluator;

    Request-scoped dependencies
    ---------------------------
    - ai_run_id;
    - telemetry repositories;
    - TelemetryRecorder;
    - purpose-specific InstrumentedLLMProvider instances;
    - IntentClassifier;
    - GroundedResponseGenerator;
    - DecisionEngine;
    - AIOrchestrator.

    Why request-scoped instrumentation?
    -----------------------------------
    InstrumentedLLMProvider contains an immutable LLMCallContext containing the ai_run_id and operation purpose.

    Sharing an instrumented wrapper between simultaneous customer requests could attribute LLM calls to the wrong AI run.

    Why multiple wrappers in one run?
    ---------------------------------
    One run can call the same underlying model for several logically distinct operations.

    For example:

        ai_run_id = X

        intent provider
            purpose = intent_classification

        generation provider
            purpose = answer_generation

    Both wrappers use the same base provider and recorder while preserving distinct telemetry identity.
    """
    def __init__(self, *, base_provider: LLMProvider, intent_classifier_config: IntentClassifierConfig | None = None,
                 decision_engine_config: DecisionEngineConfig | None = None, orchestrator_config: AIOrchestratorConfig | None = None,
                 generation_prompt_builder: GroundedGenerationPromptBuilder | None = None, guardrail_evaluator: GuardrailEvaluator | None = None,
                 observer: OrchestrationObserver | None = None, config: AIPipelineFactoryConfig | None = None) -> None:
        if not isinstance(base_provider, LLMProvider):
            raise TypeError("base_provider must implement LLMProvider")

        if intent_classifier_config is not None and not isinstance(intent_classifier_config, IntentClassifierConfig):
            raise TypeError("intent_classifier_config must be an IntentClassifierConfig instance or None")

        if decision_engine_config is not None and not isinstance(decision_engine_config, DecisionEngineConfig):
            raise TypeError("decision_engine_config must be a DecisionEngineConfig instance or None")

        if orchestrator_config is not None and not isinstance(orchestrator_config, AIOrchestratorConfig):
            raise TypeError("orchestrator_config must be an AIOrchestratorConfig instance or None")

        if generation_prompt_builder is not None and not isinstance(generation_prompt_builder, GroundedGenerationPromptBuilder):
            raise TypeError("generation_prompt_builder must be a GroundedGenerationPromptBuilder instance or None")
        
        if guardrail_evaluator is not None and not isinstance(guardrail_evaluator, GuardrailEvaluator):
            raise TypeError("guardrail_evaluator must be a GuardrailEvaluator instance or None")

        if config is not None and not isinstance(config, AIPipelineFactoryConfig):
            raise TypeError("config must be an AIPipelineFactoryConfig instance or None")

        self._base_provider = base_provider
        self._intent_classifier_config = intent_classifier_config or IntentClassifierConfig()
        self._decision_engine_config = decision_engine_config or DecisionEngineConfig()
        self._orchestrator_config = orchestrator_config or AIOrchestratorConfig()
        self._generation_prompt_builder = generation_prompt_builder or GroundedGenerationPromptBuilder()
        self._guardrail_evaluator = guardrail_evaluator if guardrail_evaluator is not None else GuardrailEvaluator()
        self._observer = observer
        self._config = config or AIPipelineFactoryConfig()

    # Public construction API
    def create(self, *, ai_run_id: uuid.UUID, repositories: AITelemetryRepositories, answer_service_builder: AnswerServiceBuilder | None = None) -> AIPipeline:
        """
        Construct all request-scoped AI dependencies for one AI run.

        All repositories must already belong to the caller's active UnitOfWork/session.

        This method does not perform any provider call or database commit.
        """
        if not isinstance(ai_run_id, uuid.UUID):
            raise TypeError("ai_run_id must be a UUID")

        if not isinstance(repositories, AITelemetryRepositories):
            raise TypeError("repositories must be an AITelemetryRepositories")

        recorder = self._create_telemetry_recorder(repositories=repositories)
        intent_provider = self._create_instrumented_provider(
            ai_run_id=ai_run_id,
            recorder=recorder,
            purpose=self._config.intent_purpose,
            prompt_version_id=self._config.intent_prompt_version_id,
            temperature=self._config.intent_temperature
        )
        generation_provider = self._create_instrumented_provider(
            ai_run_id=ai_run_id,
            recorder=recorder,
            purpose=self._config.generation_purpose,
            prompt_version_id=self._config.generation_prompt_version_id,
            temperature=self._config.generation_temperature,
        )
        intent_classifier = IntentClassifier(provider=intent_provider, config=self._intent_classifier_config)
        decision_engine = DecisionEngine(config=self._decision_engine_config)
        grounded_response_generator = GroundedResponseGenerator(
            provider=generation_provider,
            prompt_builder=self._generation_prompt_builder,
        )

        answer_service = answer_service_builder(grounded_response_generator) if answer_service_builder is not None else None
        if answer_service is not None and not isinstance(answer_service, AnswerService):
            raise TypeError("answer_service_builder must return an AnswerService")

        orchestrator = AIOrchestrator(
            intent_classifier=intent_classifier,
            decision_engine=decision_engine,
            answer_service=answer_service,
            guardrail_evaluator=self._guardrail_evaluator,
            observer=self._observer,
            config=self._orchestrator_config,
        )

        return AIPipeline(
            orchestrator=orchestrator,
            intent_classifier=intent_classifier,
            decision_engine=decision_engine,
            grounded_response_generator=grounded_response_generator,
            guardrail_evaluator=self._guardrail_evaluator,
            intent_provider=intent_provider,
            generation_provider=generation_provider,
            telemetry_recorder=recorder,
        )

    # Internal composition helpers
    @staticmethod
    def _create_telemetry_recorder(*, repositories: AITelemetryRepositories) -> TelemetryRecorder:
        return TelemetryRecorder(
            llm_calls=repositories.llm_calls,
            intent_predictions=repositories.intent_predictions,
            ai_decisions=repositories.ai_decisions,
        )

    def _create_instrumented_provider(self, *, ai_run_id: uuid.UUID, recorder: TelemetryRecorder, purpose: str,
                                      prompt_version_id: uuid.UUID | None, temperature: Decimal | None) -> InstrumentedLLMProvider:
        """
        Build one purpose-scoped instrumentation decorator.

        The underlying provider is deliberately shared. Only the immutable execution context differs between logical LLM operations.
        """
        return InstrumentedLLMProvider(
            provider=self._base_provider,
            recorder=recorder,
            context=LLMCallContext(ai_run_id=ai_run_id, purpose=purpose, prompt_version_id=prompt_version_id, temperature=temperature),
        )

    # Read-only metadata
    @property
    def provider_name(self) -> str:
        return self._base_provider.provider_name

    @property
    def model_name(self) -> str:
        return self._base_provider.model_name

    @property
    def base_provider(self) -> LLMProvider:
        """
        Expose the configured long-lived provider for health checks and application diagnostics.

        The provider reference cannot be replaced through this property.
        """
        return self._base_provider

    @property
    def pipeline_version(self) -> str:
        return self._orchestrator_config.pipeline_version