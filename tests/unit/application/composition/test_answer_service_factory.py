from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from packages.ai.generation.generator import (
    GroundedResponseGenerator,
)
from packages.application.ai.answer_service import (
    AnswerService,
)
from packages.application.composition.answer_service_factory import (
    AnswerServiceComponents,
    create_answer_service_components,
)
from packages.application.composition.knowledge_application_factory import (
    KnowledgeApplicationComponents,
)
from packages.application.composition.knowledge_retrieval_factory import (
    KnowledgeRetrievalComponents,
)
from packages.application.knowledge.evidence_mapper import (
    KnowledgeEvidenceMapper,
)
from packages.application.knowledge.retrieval_context_service import (
    KnowledgeRetrievalContextService,
)
from packages.knowledge.retrieval.application.build_grounding_context import (
    BuildGroundingContext,
)
from packages.knowledge.retrieval.application.retrieve_knowledge import (
    RetrieveKnowledge,
)
from packages.knowledge.retrieval.context.builder import (
    GroundingContextBuilder,
)
from packages.knowledge.retrieval.context.models import (
    GroundingContextBudget,
)
from packages.knowledge.retrieval.lexical.service import (
    LexicalRetrievalService,
)
from packages.knowledge.retrieval.profiles import (
    RetrievalProfile,
)
from packages.knowledge.retrieval.query.service import (
    RetrievalQueryPreparationService,
)
from packages.knowledge.retrieval.reranking.service import (
    RerankingService,
)
from packages.knowledge.retrieval.vector.service import (
    VectorRetrievalService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session() -> MagicMock:
    return MagicMock(
        spec_set=Session,
    )


@pytest.fixture
def profile() -> MagicMock:
    return MagicMock(
        spec_set=RetrievalProfile,
    )


@pytest.fixture
def context_budget() -> MagicMock:
    return MagicMock(
        spec_set=GroundingContextBudget,
    )


@pytest.fixture
def response_generator() -> MagicMock:
    return MagicMock(
        spec_set=GroundedResponseGenerator,
    )


@pytest.fixture
def retrieval_context_service() -> MagicMock:
    return MagicMock(
        spec_set=KnowledgeRetrievalContextService,
    )


@pytest.fixture
def query_preparation_service() -> MagicMock:
    return MagicMock(
        spec_set=RetrievalQueryPreparationService,
    )


@pytest.fixture
def retrieve_knowledge() -> MagicMock:
    return MagicMock(
        spec_set=RetrieveKnowledge,
    )


@pytest.fixture
def build_grounding_context() -> MagicMock:
    return MagicMock(
        spec_set=BuildGroundingContext,
    )


@pytest.fixture
def vector_service() -> MagicMock:
    return MagicMock(
        spec_set=VectorRetrievalService,
    )


@pytest.fixture
def lexical_service() -> MagicMock:
    return MagicMock(
        spec_set=LexicalRetrievalService,
    )


@pytest.fixture
def reranking_service() -> MagicMock:
    return MagicMock(
        spec_set=RerankingService,
    )


@pytest.fixture
def context_builder() -> MagicMock:
    return MagicMock(
        spec_set=GroundingContextBuilder,
    )


@pytest.fixture
def knowledge_application(
    retrieval_context_service,
) -> KnowledgeApplicationComponents:
    return KnowledgeApplicationComponents(
        retrieval_context_service=(
            retrieval_context_service
        ),
    )


@pytest.fixture
def knowledge_retrieval(
    query_preparation_service,
    retrieve_knowledge,
    build_grounding_context,
    vector_service,
    lexical_service,
    reranking_service,
    context_builder,
) -> KnowledgeRetrievalComponents:
    return KnowledgeRetrievalComponents(
        query_preparation_service=(
            query_preparation_service
        ),
        retrieve_knowledge=retrieve_knowledge,
        build_grounding_context=(
            build_grounding_context
        ),
        vector_service=vector_service,
        lexical_service=lexical_service,
        reranking_service=reranking_service,
        context_builder=context_builder,
    )


@pytest.fixture
def evidence_mapper() -> KnowledgeEvidenceMapper:
    return KnowledgeEvidenceMapper()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_with_injected_components(
    *,
    session,
    profile,
    context_budget,
    response_generator,
    knowledge_application,
    knowledge_retrieval,
    evidence_mapper,
) -> AnswerServiceComponents:
    return create_answer_service_components(
        session=session,
        profile=profile,
        default_context_budget=context_budget,
        response_generator=response_generator,
        knowledge_application=knowledge_application,
        knowledge_retrieval=knowledge_retrieval,
        evidence_mapper=evidence_mapper,
    )


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


class TestAnswerServiceComponents:

    def test_result_is_frozen(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
        evidence_mapper,
    ):
        components = create_with_injected_components(
            session=session,
            profile=profile,
            context_budget=context_budget,
            response_generator=response_generator,
            knowledge_application=knowledge_application,
            knowledge_retrieval=knowledge_retrieval,
            evidence_mapper=evidence_mapper,
        )

        with pytest.raises(
            (AttributeError, TypeError),
        ):
            components.answer_service = None

    def test_result_exposes_expected_components(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
        evidence_mapper,
    ):
        components = create_with_injected_components(
            session=session,
            profile=profile,
            context_budget=context_budget,
            response_generator=response_generator,
            knowledge_application=knowledge_application,
            knowledge_retrieval=knowledge_retrieval,
            evidence_mapper=evidence_mapper,
        )

        assert isinstance(
            components,
            AnswerServiceComponents,
        )

        assert isinstance(
            components.answer_service,
            AnswerService,
        )

        assert (
            components.knowledge_application
            is knowledge_application
        )

        assert (
            components.knowledge_retrieval
            is knowledge_retrieval
        )

        assert (
            components.evidence_mapper
            is evidence_mapper
        )


# ---------------------------------------------------------------------------
# Explicit dependency reuse
# ---------------------------------------------------------------------------


class TestInjectedComposition:

    def test_reuses_injected_component_bundles(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
        evidence_mapper,
    ):
        components = create_with_injected_components(
            session=session,
            profile=profile,
            context_budget=context_budget,
            response_generator=response_generator,
            knowledge_application=knowledge_application,
            knowledge_retrieval=knowledge_retrieval,
            evidence_mapper=evidence_mapper,
        )

        assert (
            components.knowledge_application
            is knowledge_application
        )

        assert (
            components.knowledge_retrieval
            is knowledge_retrieval
        )

        assert (
            components.evidence_mapper
            is evidence_mapper
        )

    def test_does_not_rebuild_injected_bundles(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
        evidence_mapper,
    ):
        factory_module = (
            "packages.application.composition."
            "answer_service_factory"
        )

        with (
            patch(
                f"{factory_module}."
                "create_knowledge_application_components"
            ) as application_factory,
            patch(
                f"{factory_module}."
                "create_knowledge_retrieval_components"
            ) as retrieval_factory,
        ):
            create_with_injected_components(
                session=session,
                profile=profile,
                context_budget=context_budget,
                response_generator=response_generator,
                knowledge_application=(
                    knowledge_application
                ),
                knowledge_retrieval=(
                    knowledge_retrieval
                ),
                evidence_mapper=evidence_mapper,
            )

        application_factory.assert_not_called()
        retrieval_factory.assert_not_called()


# ---------------------------------------------------------------------------
# AnswerService wiring
# ---------------------------------------------------------------------------


class TestAnswerServiceWiring:

    def test_answer_service_receives_expected_dependencies(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
        evidence_mapper,
    ):
        components = create_with_injected_components(
            session=session,
            profile=profile,
            context_budget=context_budget,
            response_generator=response_generator,
            knowledge_application=knowledge_application,
            knowledge_retrieval=knowledge_retrieval,
            evidence_mapper=evidence_mapper,
        )

        service = components.answer_service

        assert (
            service._retrieval_context_service
            is knowledge_application.retrieval_context_service
        )

        assert (
            service._query_preparation_service
            is knowledge_retrieval.query_preparation_service
        )

        assert (
            service._build_grounding_context
            is knowledge_retrieval.build_grounding_context
        )

        assert (
            service._evidence_mapper
            is evidence_mapper
        )

        assert (
            service._response_generator
            is response_generator
        )


# ---------------------------------------------------------------------------
# Default composition
# ---------------------------------------------------------------------------


class TestDefaultComposition:

    def test_creates_default_application_components(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_retrieval,
    ):
        factory_module = (
            "packages.application.composition."
            "answer_service_factory"
        )

        application_components = KnowledgeApplicationComponents(
            retrieval_context_service=MagicMock(
                spec_set=KnowledgeRetrievalContextService,
            ),
        )

        with (
            patch(
                f"{factory_module}."
                "create_knowledge_application_components",
                return_value=application_components,
            ) as application_factory,
        ):
            components = (
                create_answer_service_components(
                    session=session,
                    profile=profile,
                    default_context_budget=(
                        context_budget
                    ),
                    response_generator=(
                        response_generator
                    ),
                    knowledge_retrieval=(
                        knowledge_retrieval
                    ),
                )
            )

        application_factory.assert_called_once_with()

        assert (
            components.knowledge_application
            is application_components
        )

    def test_creates_default_retrieval_components(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
    ):
        factory_module = (
            "packages.application.composition."
            "answer_service_factory"
        )

        with patch(
            f"{factory_module}."
            "create_knowledge_retrieval_components",
            return_value=knowledge_retrieval,
        ) as retrieval_factory:
            components = create_answer_service_components(
                session=session,
                profile=profile,
                default_context_budget=context_budget,
                response_generator=response_generator,
                knowledge_application=knowledge_application,
            )

        retrieval_factory.assert_called_once_with(
            session=session,
            profile=profile,
            default_context_budget=context_budget,
            embedding_provider=None,
            embedding_input_descriptor=None,
            reranker=None,
            token_estimator=None,
        )

        assert (
            components.knowledge_retrieval
            is knowledge_retrieval
        )

    def test_creates_default_evidence_mapper(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
    ):
        components = (
            create_answer_service_components(
                session=session,
                profile=profile,
                default_context_budget=(
                    context_budget
                ),
                response_generator=(
                    response_generator
                ),
                knowledge_application=(
                    knowledge_application
                ),
                knowledge_retrieval=(
                    knowledge_retrieval
                ),
            )
        )

        assert isinstance(
            components.evidence_mapper,
            KnowledgeEvidenceMapper,
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:

    @pytest.mark.parametrize(
        ("argument", "value"),
        [
            ("session", object()),
            ("profile", object()),
            (
                "default_context_budget",
                object(),
            ),
            (
                "response_generator",
                object(),
            ),
        ],
    )
    def test_rejects_invalid_core_dependency(
        self,
        argument,
        value,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
        evidence_mapper,
    ):
        kwargs = {
            "session": session,
            "profile": profile,
            "default_context_budget": (
                context_budget
            ),
            "response_generator": (
                response_generator
            ),
            "knowledge_application": (
                knowledge_application
            ),
            "knowledge_retrieval": (
                knowledge_retrieval
            ),
            "evidence_mapper": evidence_mapper,
        }

        kwargs[argument] = value

        with pytest.raises(TypeError):
            create_answer_service_components(
                **kwargs,
            )

    def test_rejects_invalid_knowledge_application(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_retrieval,
        evidence_mapper,
    ):
        with pytest.raises(
            TypeError,
            match="knowledge_application",
        ):
            create_answer_service_components(
                session=session,
                profile=profile,
                default_context_budget=(
                    context_budget
                ),
                response_generator=(
                    response_generator
                ),
                knowledge_application=object(),
                knowledge_retrieval=(
                    knowledge_retrieval
                ),
                evidence_mapper=evidence_mapper,
            )

    def test_rejects_invalid_knowledge_retrieval(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        evidence_mapper,
    ):
        with pytest.raises(
            TypeError,
            match="knowledge_retrieval",
        ):
            create_answer_service_components(
                session=session,
                profile=profile,
                default_context_budget=(
                    context_budget
                ),
                response_generator=(
                    response_generator
                ),
                knowledge_application=(
                    knowledge_application
                ),
                knowledge_retrieval=object(),
                evidence_mapper=evidence_mapper,
            )

    def test_rejects_invalid_evidence_mapper(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
    ):
        with pytest.raises(
            TypeError,
            match="evidence_mapper",
        ):
            create_answer_service_components(
                session=session,
                profile=profile,
                default_context_budget=(
                    context_budget
                ),
                response_generator=(
                    response_generator
                ),
                knowledge_application=(
                    knowledge_application
                ),
                knowledge_retrieval=(
                    knowledge_retrieval
                ),
                evidence_mapper=object(),
            )


# ---------------------------------------------------------------------------
# Side-effect guarantees
# ---------------------------------------------------------------------------


class TestCompositionSideEffects:

    def test_composition_does_not_manage_session_lifecycle(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
        evidence_mapper,
    ):
        create_with_injected_components(
            session=session,
            profile=profile,
            context_budget=context_budget,
            response_generator=response_generator,
            knowledge_application=knowledge_application,
            knowledge_retrieval=knowledge_retrieval,
            evidence_mapper=evidence_mapper,
        )

        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.close.assert_not_called()

    def test_composition_does_not_call_generator(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
        evidence_mapper,
    ):
        create_with_injected_components(
            session=session,
            profile=profile,
            context_budget=context_budget,
            response_generator=response_generator,
            knowledge_application=knowledge_application,
            knowledge_retrieval=knowledge_retrieval,
            evidence_mapper=evidence_mapper,
        )

        response_generator.generate.assert_not_called()
        response_generator.generate_with_response.assert_not_called()

    def test_composition_does_not_execute_retrieval(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
        evidence_mapper,
    ):
        create_with_injected_components(
            session=session,
            profile=profile,
            context_budget=context_budget,
            response_generator=response_generator,
            knowledge_application=knowledge_application,
            knowledge_retrieval=knowledge_retrieval,
            evidence_mapper=evidence_mapper,
        )

        knowledge_retrieval.retrieve_knowledge.retrieve.assert_not_called()

        knowledge_retrieval.build_grounding_context.build.assert_not_called()


# ---------------------------------------------------------------------------
# Fresh composition
# ---------------------------------------------------------------------------


class TestCompositionLifetime:

    def test_each_call_creates_fresh_answer_service(
        self,
        session,
        profile,
        context_budget,
        response_generator,
        knowledge_application,
        knowledge_retrieval,
        evidence_mapper,
    ):
        first = create_with_injected_components(
            session=session,
            profile=profile,
            context_budget=context_budget,
            response_generator=response_generator,
            knowledge_application=knowledge_application,
            knowledge_retrieval=knowledge_retrieval,
            evidence_mapper=evidence_mapper,
        )

        second = create_with_injected_components(
            session=session,
            profile=profile,
            context_budget=context_budget,
            response_generator=response_generator,
            knowledge_application=knowledge_application,
            knowledge_retrieval=knowledge_retrieval,
            evidence_mapper=evidence_mapper,
        )

        assert (
            first.answer_service
            is not second.answer_service
        )

        # Explicitly injected dependencies remain shared.
        assert (
            first.knowledge_application
            is second.knowledge_application
        )

        assert (
            first.knowledge_retrieval
            is second.knowledge_retrieval
        )

        assert (
            first.evidence_mapper
            is second.evidence_mapper
        )