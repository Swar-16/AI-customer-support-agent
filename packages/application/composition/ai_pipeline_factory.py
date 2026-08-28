from __future__ import annotations
import uuid
from dataclasses import dataclass
from decimal import Decimal
from packages.ai.decision.engine import DecisionEngine, DecisionEngineConfig
from packages.ai.intent.classifier import IntentClassifier, IntentClassifierConfig
from packages.ai.orchestration.orchestrator import AIOrchestrator, AIOrchestratorConfig, OrchestrationObserver
from packages.ai.providers.base import LLMProvider
from packages.ai.providers.instrumented import InstrumentedLLMProvider, LLMCallContext
from packages.ai.telemetry.recorder import TelemetryRecorder
from packages.database.repositories.ai.decision_repository import AIDecisionRepository
from packages.database.repositories.ai.intent_prediction_repository import IntentPredictionRepository
from packages.database.repositories.ai.llm_call_repository import LLMCallRepository



# Immutable pipeline bundle
@dataclass(frozen=True, slots=True)
class AIPipeline:
    """
    Fully composed AI pipeline for one AI run.

    This object owns no transaction itself. All persistence dependencies supplied to the factory are expected to belong to the caller's active UnitOfWork.

    The bundle is useful both for production execution and integration tests.
    """

    orchestrator: AIOrchestrator
    intent_classifier: IntentClassifier
    decision_engine: DecisionEngine
    instrumented_provider: InstrumentedLLMProvider
    telemetry_recorder: TelemetryRecorder



# Repository dependencies
@dataclass(frozen=True, slots=True)
class AITelemetryRepositories:
    """
    Repository dependencies required for AI telemetry persistence.
    Keeping this as a small typed bundle avoids making the factory depend directly on SqlAlchemyUnitOfWork.
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
    Stable composition-level configuration.
    This is intentionally separate from the individual component configs.
    """

    intent_purpose: str = "intent_classification"
    intent_temperature: Decimal | None = None
    intent_prompt_version_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        normalized_purpose = self.intent_purpose.strip()
        if not normalized_purpose:
            raise ValueError("intent_purpose cannot be empty")

        object.__setattr__(self, "intent_purpose", normalized_purpose)
        if self.intent_prompt_version_id is not None and not isinstance(self.intent_prompt_version_id, uuid.UUID):
            raise TypeError("intent_prompt_version_id must be UUID or None")

        if self.intent_temperature is not None:
            if not isinstance(self.intent_temperature, Decimal):
                raise TypeError("intent_temperature must be Decimal or None")

            if not Decimal("0") <= self.intent_temperature <= Decimal("2"):
                raise ValueError("intent_temperature must be between 0 and 2")

# Factory
class AIPipelineFactory:
    """
    Builds a request-scoped AI pipeline.

    Long-lived dependencies:
        base provider
        component configuration
        optional orchestration observer

    Request-scoped dependencies:
        ai_run_id
        repositories / active UnitOfWork session
        telemetry recorder
        instrumented provider
        classifier
        orchestrator

    Why request-scoped?

    InstrumentedLLMProvider contains LLMCallContext.ai_run_id.
    Sharing one instrumented wrapper across simultaneous requests would risk
    associating telemetry with the wrong AI run.

    The underlying base provider itself may still be safely long-lived.
    """

    def __init__(self, *,base_provider: LLMProvider, intent_classifier_config: IntentClassifierConfig | None = None,
                 decision_engine_config: DecisionEngineConfig | None = None, orchestrator_config: AIOrchestratorConfig | None = None,
                 observer: OrchestrationObserver | None = None, config: AIPipelineFactoryConfig | None = None,
    ) -> None:
        if not isinstance(base_provider, LLMProvider):
            raise TypeError("base_provider must implement LLMProvider")

        self._base_provider = base_provider
        self._intent_classifier_config = intent_classifier_config or IntentClassifierConfig()
        self._decision_engine_config = decision_engine_config or DecisionEngineConfig()
        self._orchestrator_config = orchestrator_config or AIOrchestratorConfig()
        self._observer = observer
        self._config = config or AIPipelineFactoryConfig()

    # Public construction API
    def create(self, *, ai_run_id: uuid.UUID, repositories: AITelemetryRepositories) -> AIPipeline:
        """
        Construct the complete pipeline for one AI run.
        All repositories must belong to the same active UnitOfWork/session.
        """
        if not isinstance(ai_run_id, uuid.UUID):
            raise TypeError("ai_run_id must be a UUID")

        if not isinstance(repositories, AITelemetryRepositories):
            raise TypeError("repositories must be an AITelemetryRepositories")

        recorder = TelemetryRecorder(
            llm_calls=repositories.llm_calls,
            intent_predictions=repositories.intent_predictions,
            ai_decisions=repositories.ai_decisions,
        )

        instrumented_provider = (
            InstrumentedLLMProvider(
                provider=self._base_provider,
                recorder=recorder,
                context=LLMCallContext(
                    ai_run_id=ai_run_id,
                    purpose=self._config.intent_purpose,
                    prompt_version_id=self._config.intent_prompt_version_id,
                    temperature=self._config.intent_temperature,
                ),
            )
        )

        intent_classifier = IntentClassifier(
            provider=instrumented_provider,
            config=self._intent_classifier_config,
        )

        decision_engine = DecisionEngine(config=self._decision_engine_config)

        orchestrator = AIOrchestrator(
            intent_classifier=intent_classifier,
            decision_engine=decision_engine,
            observer=self._observer,
            config=self._orchestrator_config,
        )

        return AIPipeline(
            orchestrator=orchestrator,
            intent_classifier=intent_classifier,
            decision_engine=decision_engine,
            instrumented_provider=instrumented_provider,
            telemetry_recorder=recorder,
        )

    # Read-only metadata
    @property
    def provider_name(self) -> str:
        return self._base_provider.provider_name

    @property
    def base_provider(self) -> LLMProvider:
        """
        Expose the configured provider without allowing replacement.
        
        Primarily useful for health checks and application diagnostics.
        """
        return self._base_provider
    
    @property
    def model_name(self) -> str:
        return self._base_provider.model_name

    @property
    def pipeline_version(self) -> str:
        return self._orchestrator_config.pipeline_version