from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from decimal import Decimal
from unittest.mock import MagicMock, create_autospec

import pytest

from packages.ai.decision.engine import (
    DecisionEngine,
    DecisionEngineConfig,
)
from packages.ai.generation.generator import GroundedResponseGenerator
from packages.ai.generation.prompts import (
    GroundedGenerationPromptBuilder,
)
from packages.ai.intent.classifier import (
    IntentClassifier,
    IntentClassifierConfig,
)
from packages.ai.orchestration.orchestrator import (
    AIOrchestrator,
    AIOrchestratorConfig,
)
from packages.ai.providers.base import LLMProvider
from packages.ai.providers.instrumented import (
    InstrumentedLLMProvider,
)
from packages.ai.telemetry.recorder import TelemetryRecorder
from packages.application.ai.answer_service import AnswerService
from packages.application.composition.ai_pipeline_factory import (
    AIPipeline,
    AIPipelineFactory,
    AIPipelineFactoryConfig,
    AITelemetryRepositories,
)
from packages.database.repositories.ai.decision_repository import (
    AIDecisionRepository,
)
from packages.database.repositories.ai.intent_prediction_repository import (
    IntentPredictionRepository,
)
from packages.database.repositories.ai.llm_call_repository import (
    LLMCallRepository,
)


class StubAnswerService(AnswerService):
    """
    Minimal typed AnswerService test double.

    AIPipelineFactory validates the builder result with ``isinstance``.
    Subclassing keeps that production contract active without constructing
    the real retrieval/generation dependency graph in this composition suite.
    """

    def __init__(self) -> None:
        # Intentionally do not call AnswerService.__init__().
        # This suite only verifies composition identity, not AnswerService
        # behavior, which is covered by its dedicated unit tests.
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_provider():
    """
    Provider is fully mocked because composition must never make a real
    network call.
    """
    provider = create_autospec(
        LLMProvider,
        instance=True,
    )

    provider.provider_name = "mock"
    provider.model_name = "mock-llm-v1"

    return provider


@pytest.fixture
def repositories():
    """
    Repository mocks satisfy the concrete repository contracts while avoiding
    any database dependency in this unit-test suite.
    """
    return AITelemetryRepositories(
        llm_calls=create_autospec(
            LLMCallRepository,
            instance=True,
        ),
        intent_predictions=create_autospec(
            IntentPredictionRepository,
            instance=True,
        ),
        ai_decisions=create_autospec(
            AIDecisionRepository,
            instance=True,
        ),
    )


@pytest.fixture
def factory(base_provider):
    return AIPipelineFactory(
        base_provider=base_provider,
    )


@pytest.fixture
def answer_service():
    return StubAnswerService()


def make_pipeline(
    factory: AIPipelineFactory,
    repositories: AITelemetryRepositories,
    *,
    ai_run_id: uuid.UUID | None = None,
    answer_service_builder=None,
) -> tuple[uuid.UUID, AIPipeline]:
    resolved_run_id = ai_run_id or uuid.uuid4()

    pipeline = factory.create(
        ai_run_id=resolved_run_id,
        repositories=repositories,
        answer_service_builder=answer_service_builder,
    )

    return resolved_run_id, pipeline


# ===========================================================================
# Repository dependency contract
# ===========================================================================


class TestAITelemetryRepositories:
    def test_valid_repository_bundle_is_constructed(
        self,
        repositories,
    ):
        assert isinstance(
            repositories,
            AITelemetryRepositories,
        )

    def test_rejects_invalid_llm_call_repository(self):
        with pytest.raises(
            TypeError,
            match="llm_calls",
        ):
            AITelemetryRepositories(
                llm_calls=object(),  # type: ignore[arg-type]
                intent_predictions=create_autospec(
                    IntentPredictionRepository,
                    instance=True,
                ),
                ai_decisions=create_autospec(
                    AIDecisionRepository,
                    instance=True,
                ),
            )

    def test_rejects_invalid_intent_prediction_repository(self):
        with pytest.raises(
            TypeError,
            match="intent_predictions",
        ):
            AITelemetryRepositories(
                llm_calls=create_autospec(
                    LLMCallRepository,
                    instance=True,
                ),
                intent_predictions=object(),  # type: ignore[arg-type]
                ai_decisions=create_autospec(
                    AIDecisionRepository,
                    instance=True,
                ),
            )

    def test_rejects_invalid_decision_repository(self):
        with pytest.raises(
            TypeError,
            match="ai_decisions",
        ):
            AITelemetryRepositories(
                llm_calls=create_autospec(
                    LLMCallRepository,
                    instance=True,
                ),
                intent_predictions=create_autospec(
                    IntentPredictionRepository,
                    instance=True,
                ),
                ai_decisions=object(),  # type: ignore[arg-type]
            )

    def test_repository_bundle_is_immutable(
        self,
        repositories,
    ):
        with pytest.raises(
            (FrozenInstanceError, AttributeError),
        ):
            repositories.llm_calls = object()  # type: ignore[misc]


# ===========================================================================
# Factory configuration defaults
# ===========================================================================


class TestAIPipelineFactoryConfigDefaults:
    def test_default_intent_purpose(self):
        config = AIPipelineFactoryConfig()

        assert (
            config.intent_purpose
            == "intent_classification"
        )

    def test_default_generation_purpose(self):
        config = AIPipelineFactoryConfig()

        assert (
            config.generation_purpose
            == "answer_generation"
        )

    def test_default_temperatures_are_none(self):
        config = AIPipelineFactoryConfig()

        assert config.intent_temperature is None
        assert config.generation_temperature is None

    def test_default_prompt_version_ids_are_none(self):
        config = AIPipelineFactoryConfig()

        assert config.intent_prompt_version_id is None
        assert (
            config.generation_prompt_version_id
            is None
        )

    def test_config_is_immutable(self):
        config = AIPipelineFactoryConfig()

        with pytest.raises(
            (FrozenInstanceError, AttributeError),
        ):
            config.intent_purpose = "changed"  # type: ignore[misc]


# ===========================================================================
# Purpose validation
# ===========================================================================


class TestAIPipelineFactoryPurposeValidation:
    @pytest.mark.parametrize(
        "field_name",
        [
            "intent_purpose",
            "generation_purpose",
        ],
    )
    def test_empty_purpose_rejected(
        self,
        field_name,
    ):
        kwargs = {
            field_name: "   ",
        }

        with pytest.raises(
            ValueError,
            match="cannot be empty",
        ):
            AIPipelineFactoryConfig(**kwargs)

    @pytest.mark.parametrize(
        "field_name",
        [
            "intent_purpose",
            "generation_purpose",
        ],
    )
    def test_non_string_purpose_rejected(
        self,
        field_name,
    ):
        kwargs = {
            field_name: 123,
        }

        with pytest.raises(
            TypeError,
            match="must be a string",
        ):
            AIPipelineFactoryConfig(
                **kwargs,  # type: ignore[arg-type]
            )

    def test_purposes_are_normalized(self):
        config = AIPipelineFactoryConfig(
            intent_purpose="  classify_customer  ",
            generation_purpose="  generate_answer  ",
        )

        assert (
            config.intent_purpose
            == "classify_customer"
        )
        assert (
            config.generation_purpose
            == "generate_answer"
        )

    def test_identical_purposes_rejected(self):
        with pytest.raises(
            ValueError,
            match="must be distinct",
        ):
            AIPipelineFactoryConfig(
                intent_purpose="same",
                generation_purpose="same",
            )

    def test_identical_purposes_after_normalization_rejected(
        self,
    ):
        with pytest.raises(
            ValueError,
            match="must be distinct",
        ):
            AIPipelineFactoryConfig(
                intent_purpose=" operation ",
                generation_purpose="operation",
            )


# ===========================================================================
# Temperature configuration
# ===========================================================================


class TestAIPipelineFactoryTemperatureValidation:
    @pytest.mark.parametrize(
        "field_name",
        [
            "intent_temperature",
            "generation_temperature",
        ],
    )
    def test_non_decimal_temperature_rejected(
        self,
        field_name,
    ):
        with pytest.raises(
            TypeError,
            match="Decimal",
        ):
            AIPipelineFactoryConfig(
                **{
                    field_name: 0.2,
                }  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "field_name",
        [
            "intent_temperature",
            "generation_temperature",
        ],
    )
    @pytest.mark.parametrize(
        "value",
        [
            Decimal("-0.01"),
            Decimal("2.01"),
        ],
    )
    def test_out_of_range_temperature_rejected(
        self,
        field_name,
        value,
    ):
        with pytest.raises(
            ValueError,
            match="between 0 and 2",
        ):
            AIPipelineFactoryConfig(
                **{
                    field_name: value,
                }
            )

    @pytest.mark.parametrize(
        "value",
        [
            Decimal("0"),
            Decimal("0.25"),
            Decimal("1"),
            Decimal("2"),
        ],
    )
    def test_valid_temperatures_are_accepted(
        self,
        value,
    ):
        config = AIPipelineFactoryConfig(
            intent_temperature=value,
            generation_temperature=value,
        )

        assert config.intent_temperature == value
        assert config.generation_temperature == value


# ===========================================================================
# Prompt version configuration
# ===========================================================================


class TestPromptVersionValidation:
    def test_valid_prompt_version_ids_are_preserved(
        self,
    ):
        intent_version = uuid.uuid4()
        generation_version = uuid.uuid4()

        config = AIPipelineFactoryConfig(
            intent_prompt_version_id=intent_version,
            generation_prompt_version_id=(
                generation_version
            ),
        )

        assert (
            config.intent_prompt_version_id
            == intent_version
        )
        assert (
            config.generation_prompt_version_id
            == generation_version
        )

    @pytest.mark.parametrize(
        "field_name",
        [
            "intent_prompt_version_id",
            "generation_prompt_version_id",
        ],
    )
    def test_non_uuid_prompt_version_rejected(
        self,
        field_name,
    ):
        with pytest.raises(
            TypeError,
            match="UUID",
        ):
            AIPipelineFactoryConfig(
                **{
                    field_name: "version-1",
                }  # type: ignore[arg-type]
            )


# ===========================================================================
# Factory construction validation
# ===========================================================================


class TestAIPipelineFactoryConstruction:
    def test_requires_llm_provider(self):
        with pytest.raises(
            TypeError,
            match="base_provider",
        ):
            AIPipelineFactory(
                base_provider=object(),  # type: ignore[arg-type]
            )

    def test_rejects_invalid_intent_classifier_config(
        self,
        base_provider,
    ):
        with pytest.raises(
            TypeError,
            match="intent_classifier_config",
        ):
            AIPipelineFactory(
                base_provider=base_provider,
                intent_classifier_config=object(),  # type: ignore[arg-type]
            )

    def test_rejects_invalid_decision_engine_config(
        self,
        base_provider,
    ):
        with pytest.raises(
            TypeError,
            match="decision_engine_config",
        ):
            AIPipelineFactory(
                base_provider=base_provider,
                decision_engine_config=object(),  # type: ignore[arg-type]
            )

    def test_rejects_invalid_orchestrator_config(
        self,
        base_provider,
    ):
        with pytest.raises(
            TypeError,
            match="orchestrator_config",
        ):
            AIPipelineFactory(
                base_provider=base_provider,
                orchestrator_config=object(),  # type: ignore[arg-type]
            )

    def test_rejects_invalid_generation_prompt_builder(
        self,
        base_provider,
    ):
        with pytest.raises(
            TypeError,
            match="generation_prompt_builder",
        ):
            AIPipelineFactory(
                base_provider=base_provider,
                generation_prompt_builder=object(),  # type: ignore[arg-type]
            )

    def test_rejects_invalid_factory_config(
        self,
        base_provider,
    ):
        with pytest.raises(
            TypeError,
            match="config",
        ):
            AIPipelineFactory(
                base_provider=base_provider,
                config=object(),  # type: ignore[arg-type]
            )

    def test_accepts_explicit_component_configs(
        self,
        base_provider,
    ):
        factory = AIPipelineFactory(
            base_provider=base_provider,
            intent_classifier_config=(
                IntentClassifierConfig()
            ),
            decision_engine_config=(
                DecisionEngineConfig()
            ),
            orchestrator_config=(
                AIOrchestratorConfig()
            ),
            generation_prompt_builder=(
                GroundedGenerationPromptBuilder()
            ),
            config=AIPipelineFactoryConfig(),
        )

        assert isinstance(
            factory,
            AIPipelineFactory,
        )


# ===========================================================================
# create() input validation
# ===========================================================================


class TestAIPipelineFactoryCreateValidation:
    def test_invalid_ai_run_id_rejected(
        self,
        factory,
        repositories,
    ):
        with pytest.raises(
            TypeError,
            match="ai_run_id",
        ):
            factory.create(
                ai_run_id="not-uuid",  # type: ignore[arg-type]
                repositories=repositories,
            )

    def test_invalid_repository_bundle_rejected(
        self,
        factory,
    ):
        with pytest.raises(
            TypeError,
            match="repositories",
        ):
            factory.create(
                ai_run_id=uuid.uuid4(),
                repositories=object(),  # type: ignore[arg-type]
            )


# ===========================================================================
# AnswerService builder composition
# ===========================================================================


class TestAnswerServiceBuilderComposition:
    def test_builder_is_optional_and_preserves_backward_compatibility(
        self,
        factory,
        repositories,
    ):
        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert pipeline.orchestrator._answer_service is None

    def test_builder_is_called_exactly_once(
        self,
        factory,
        repositories,
        answer_service,
    ):
        builder = MagicMock(return_value=answer_service)

        make_pipeline(
            factory,
            repositories,
            answer_service_builder=builder,
        )

        builder.assert_called_once()

    def test_builder_receives_exact_grounded_response_generator(
        self,
        factory,
        repositories,
        answer_service,
    ):
        builder = MagicMock(return_value=answer_service)

        _, pipeline = make_pipeline(
            factory,
            repositories,
            answer_service_builder=builder,
        )

        supplied_generator = builder.call_args.args[0]

        assert (
            supplied_generator
            is pipeline.grounded_response_generator
        )

    def test_builder_result_is_injected_into_orchestrator(
        self,
        factory,
        repositories,
        answer_service,
    ):
        builder = MagicMock(return_value=answer_service)

        _, pipeline = make_pipeline(
            factory,
            repositories,
            answer_service_builder=builder,
        )

        assert (
            pipeline.orchestrator._answer_service
            is answer_service
        )

    def test_invalid_builder_result_is_rejected(
        self,
        factory,
        repositories,
    ):
        builder = MagicMock(return_value=object())

        with pytest.raises(
            TypeError,
            match=(
                "answer_service_builder must return "
                "an AnswerService"
            ),
        ):
            make_pipeline(
                factory,
                repositories,
                answer_service_builder=builder,
            )

        builder.assert_called_once()

    def test_builder_returning_none_leaves_answer_service_unconfigured(
        self,
        factory,
        repositories,
    ):
        builder = MagicMock(return_value=None)

        _, pipeline = make_pipeline(
            factory,
            repositories,
            answer_service_builder=builder,
        )

        builder.assert_called_once()
        assert pipeline.orchestrator._answer_service is None

    def test_builder_exception_propagates(
        self,
        factory,
        repositories,
    ):
        builder = MagicMock(
            side_effect=RuntimeError(
                "answer-service composition failed"
            )
        )

        with pytest.raises(
            RuntimeError,
            match="answer-service composition failed",
        ):
            make_pipeline(
                factory,
                repositories,
                answer_service_builder=builder,
            )

        builder.assert_called_once()

    def test_builder_runs_after_generation_provider_is_composed(
        self,
        factory,
        repositories,
        answer_service,
    ):
        observed = {}

        def builder(generator):
            observed["generator"] = generator
            observed["provider"] = generator._provider
            return answer_service

        _, pipeline = make_pipeline(
            factory,
            repositories,
            answer_service_builder=builder,
        )

        assert (
            observed["generator"]
            is pipeline.grounded_response_generator
        )
        assert (
            observed["provider"]
            is pipeline.generation_provider
        )

    def test_answer_service_composition_does_not_change_provider_isolation(
        self,
        factory,
        repositories,
        answer_service,
    ):
        _, pipeline = make_pipeline(
            factory,
            repositories,
            answer_service_builder=(
                lambda _generator: answer_service
            ),
        )

        assert (
            pipeline.intent_classifier._provider
            is pipeline.intent_provider
        )
        assert (
            pipeline.grounded_response_generator._provider
            is pipeline.generation_provider
        )
        assert (
            pipeline.intent_provider
            is not pipeline.generation_provider
        )


# ===========================================================================
# Pipeline composition
# ===========================================================================


class TestAIPipelineComposition:
    def test_create_returns_complete_pipeline(
        self,
        factory,
        repositories,
    ):
        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert isinstance(
            pipeline,
            AIPipeline,
        )

        assert isinstance(
            pipeline.orchestrator,
            AIOrchestrator,
        )

        assert isinstance(
            pipeline.intent_classifier,
            IntentClassifier,
        )

        assert isinstance(
            pipeline.decision_engine,
            DecisionEngine,
        )

        assert isinstance(
            pipeline.grounded_response_generator,
            GroundedResponseGenerator,
        )

        assert isinstance(
            pipeline.intent_provider,
            InstrumentedLLMProvider,
        )

        assert isinstance(
            pipeline.generation_provider,
            InstrumentedLLMProvider,
        )

        assert isinstance(
            pipeline.telemetry_recorder,
            TelemetryRecorder,
        )

    def test_pipeline_bundle_is_immutable(
        self,
        factory,
        repositories,
    ):
        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        with pytest.raises(
            (FrozenInstanceError, AttributeError),
        ):
            pipeline.intent_provider = object()  # type: ignore[misc]

    def test_intent_and_generation_providers_are_distinct(
        self,
        factory,
        repositories,
    ):
        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.intent_provider
            is not pipeline.generation_provider
        )

    def test_compatibility_alias_points_to_intent_provider(
        self,
        factory,
        repositories,
    ):
        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.instrumented_provider
            is pipeline.intent_provider
        )


# ===========================================================================
# Provider wiring invariants
# ===========================================================================


class TestProviderWiring:
    def test_both_wrappers_share_same_base_provider(
        self,
        base_provider,
        repositories,
    ):
        factory = AIPipelineFactory(
            base_provider=base_provider,
        )

        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.intent_provider._provider
            is base_provider
        )
        assert (
            pipeline.generation_provider._provider
            is base_provider
        )

    def test_both_wrappers_share_same_recorder(
        self,
        factory,
        repositories,
    ):
        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.intent_provider._recorder
            is pipeline.telemetry_recorder
        )

        assert (
            pipeline.generation_provider._recorder
            is pipeline.telemetry_recorder
        )

    def test_both_wrappers_receive_same_ai_run_id(
        self,
        factory,
        repositories,
    ):
        ai_run_id, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.intent_provider._context.ai_run_id
            == ai_run_id
        )

        assert (
            pipeline.generation_provider._context.ai_run_id
            == ai_run_id
        )

    def test_default_purposes_are_distinct_and_correct(
        self,
        factory,
        repositories,
    ):
        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.intent_provider._context.purpose
            == "intent_classification"
        )

        assert (
            pipeline.generation_provider._context.purpose
            == "answer_generation"
        )

    def test_custom_purpose_configuration_reaches_contexts(
        self,
        base_provider,
        repositories,
    ):
        factory = AIPipelineFactory(
            base_provider=base_provider,
            config=AIPipelineFactoryConfig(
                intent_purpose="intent_v2",
                generation_purpose="answer_v2",
            ),
        )

        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.intent_provider._context.purpose
            == "intent_v2"
        )
        assert (
            pipeline.generation_provider._context.purpose
            == "answer_v2"
        )

    def test_temperature_metadata_reaches_correct_context(
        self,
        base_provider,
        repositories,
    ):
        factory = AIPipelineFactory(
            base_provider=base_provider,
            config=AIPipelineFactoryConfig(
                intent_temperature=Decimal("0.1"),
                generation_temperature=Decimal("0.3"),
            ),
        )

        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.intent_provider._context.temperature
            == Decimal("0.1")
        )

        assert (
            pipeline.generation_provider._context.temperature
            == Decimal("0.3")
        )

    def test_prompt_version_ids_reach_correct_context(
        self,
        base_provider,
        repositories,
    ):
        intent_version = uuid.uuid4()
        generation_version = uuid.uuid4()

        factory = AIPipelineFactory(
            base_provider=base_provider,
            config=AIPipelineFactoryConfig(
                intent_prompt_version_id=intent_version,
                generation_prompt_version_id=(
                    generation_version
                ),
            ),
        )

        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.intent_provider._context.prompt_version_id
            == intent_version
        )

        assert (
            pipeline.generation_provider._context.prompt_version_id
            == generation_version
        )


# ===========================================================================
# Component-to-provider wiring
# ===========================================================================


class TestComponentProviderIsolation:
    def test_classifier_uses_intent_provider(
        self,
        factory,
        repositories,
    ):
        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.intent_classifier._provider
            is pipeline.intent_provider
        )

    def test_generator_uses_generation_provider(
        self,
        factory,
        repositories,
    ):
        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.grounded_response_generator._provider
            is pipeline.generation_provider
        )

    def test_classifier_does_not_use_generation_provider(
        self,
        factory,
        repositories,
    ):
        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.intent_classifier._provider
            is not pipeline.generation_provider
        )

    def test_generator_does_not_use_intent_provider(
        self,
        factory,
        repositories,
    ):
        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.grounded_response_generator._provider
            is not pipeline.intent_provider
        )

    def test_explicit_prompt_builder_is_given_to_generator(
        self,
        base_provider,
        repositories,
    ):
        prompt_builder = (
            GroundedGenerationPromptBuilder()
        )

        factory = AIPipelineFactory(
            base_provider=base_provider,
            generation_prompt_builder=prompt_builder,
        )

        _, pipeline = make_pipeline(
            factory,
            repositories,
        )

        assert (
            pipeline.grounded_response_generator._prompt_builder
            is prompt_builder
        )


# ===========================================================================
# Request-scoped lifecycle
# ===========================================================================


class TestRequestScopedLifecycle:
    def test_two_create_calls_return_distinct_pipelines(
        self,
        factory,
        repositories,
    ):
        _, first = make_pipeline(
            factory,
            repositories,
        )

        _, second = make_pipeline(
            factory,
            repositories,
        )

        assert first is not second

    def test_two_runs_receive_distinct_instrumented_providers(
        self,
        factory,
        repositories,
    ):
        _, first = make_pipeline(
            factory,
            repositories,
        )

        _, second = make_pipeline(
            factory,
            repositories,
        )

        assert (
            first.intent_provider
            is not second.intent_provider
        )

        assert (
            first.generation_provider
            is not second.generation_provider
        )

    def test_two_runs_receive_distinct_recorders(
        self,
        factory,
        repositories,
    ):
        _, first = make_pipeline(
            factory,
            repositories,
        )

        _, second = make_pipeline(
            factory,
            repositories,
        )

        assert (
            first.telemetry_recorder
            is not second.telemetry_recorder
        )

    def test_two_runs_receive_distinct_domain_components(
        self,
        factory,
        repositories,
    ):
        _, first = make_pipeline(
            factory,
            repositories,
        )

        _, second = make_pipeline(
            factory,
            repositories,
        )

        assert (
            first.intent_classifier
            is not second.intent_classifier
        )

        assert (
            first.decision_engine
            is not second.decision_engine
        )

        assert (
            first.grounded_response_generator
            is not second.grounded_response_generator
        )

        assert (
            first.orchestrator
            is not second.orchestrator
        )

    def test_different_runs_preserve_their_own_run_ids(
        self,
        factory,
        repositories,
    ):
        first_id = uuid.uuid4()
        second_id = uuid.uuid4()

        _, first = make_pipeline(
            factory,
            repositories,
            ai_run_id=first_id,
        )

        _, second = make_pipeline(
            factory,
            repositories,
            ai_run_id=second_id,
        )

        assert (
            first.intent_provider._context.ai_run_id
            == first_id
        )

        assert (
            first.generation_provider._context.ai_run_id
            == first_id
        )

        assert (
            second.intent_provider._context.ai_run_id
            == second_id
        )

        assert (
            second.generation_provider._context.ai_run_id
            == second_id
        )

    def test_same_long_lived_base_provider_is_reused_across_runs(
        self,
        base_provider,
        repositories,
    ):
        factory = AIPipelineFactory(
            base_provider=base_provider,
        )

        _, first = make_pipeline(
            factory,
            repositories,
        )

        _, second = make_pipeline(
            factory,
            repositories,
        )

        assert (
            first.intent_provider._provider
            is base_provider
        )

        assert (
            second.intent_provider._provider
            is base_provider
        )

        assert (
            first.generation_provider._provider
            is base_provider
        )

        assert (
            second.generation_provider._provider
            is base_provider
        )


# ===========================================================================
# Side-effect isolation
# ===========================================================================


class TestCompositionHasNoExecutionSideEffects:
    def test_create_does_not_call_text_generation(
        self,
        factory,
        repositories,
        base_provider,
    ):
        factory.create(
            ai_run_id=uuid.uuid4(),
            repositories=repositories,
        )

        base_provider.generate.assert_not_called()

    def test_create_does_not_call_structured_generation(
        self,
        factory,
        repositories,
        base_provider,
    ):
        factory.create(
            ai_run_id=uuid.uuid4(),
            repositories=repositories,
        )

        base_provider.generate_structured.assert_not_called()

    def test_create_does_not_health_check_provider(
        self,
        factory,
        repositories,
        base_provider,
    ):
        factory.create(
            ai_run_id=uuid.uuid4(),
            repositories=repositories,
        )

        base_provider.health_check.assert_not_called()

    def test_create_does_not_persist_llm_call(
        self,
        factory,
        repositories,
    ):
        factory.create(
            ai_run_id=uuid.uuid4(),
            repositories=repositories,
        )

        repositories.llm_calls.add.assert_not_called()


# ===========================================================================
# Factory metadata
# ===========================================================================


class TestFactoryMetadata:
    def test_provider_name_delegates_to_base_provider(
        self,
        factory,
        base_provider,
    ):
        assert (
            factory.provider_name
            == base_provider.provider_name
        )

    def test_model_name_delegates_to_base_provider(
        self,
        factory,
        base_provider,
    ):
        assert (
            factory.model_name
            == base_provider.model_name
        )

    def test_base_provider_property_preserves_identity(
        self,
        factory,
        base_provider,
    ):
        assert (
            factory.base_provider
            is base_provider
        )

    def test_pipeline_version_comes_from_orchestrator_config(
        self,
        base_provider,
    ):
        config = AIOrchestratorConfig(
            pipeline_version="v-test-42",
        )

        factory = AIPipelineFactory(
            base_provider=base_provider,
            orchestrator_config=config,
        )

        assert (
            factory.pipeline_version
            == "v-test-42"
        )