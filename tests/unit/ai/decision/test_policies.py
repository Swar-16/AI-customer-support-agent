from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest

import packages.ai.decision.policies as policies_module
from packages.ai.decision.policies import (
    DecisionPriority,
    INTENT_DECISION_POLICIES,
    IntentDecisionPolicy,
    RetrievalKind,
    get_actionable_intents,
    get_intent_decision_policy,
    get_knowledge_retrieval_intents,
    get_operational_retrieval_intents,
    validate_intent_decision_policies,
)
from packages.ai.decision.schemas import (
    DecisionReasonCode,
    DecisionType,
)
from packages.ai.intent.taxonomy import IntentType


class TestIntentDecisionPolicyValidation:
    def test_valid_knowledge_retrieval_policy(self) -> None:
        policy = IntentDecisionPolicy(
            intent=IntentType.REFUND_REQUEST,
            default_decision=DecisionType.RETRIEVE_INFORMATION,
            reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
            retrieval_kind=RetrievalKind.KNOWLEDGE,
            potentially_actionable=True,
        )

        assert policy.intent is IntentType.REFUND_REQUEST
        assert policy.default_decision is DecisionType.RETRIEVE_INFORMATION
        assert policy.retrieval_kind is RetrievalKind.KNOWLEDGE
        assert policy.potentially_actionable is True
        assert policy.default_priority is DecisionPriority.NORMAL

    def test_valid_operational_retrieval_policy(self) -> None:
        policy = IntentDecisionPolicy(
            intent=IntentType.ORDER_STATUS,
            default_decision=DecisionType.RETRIEVE_INFORMATION,
            reason_code=DecisionReasonCode.OPERATIONAL_LOOKUP_REQUIRED,
            retrieval_kind=RetrievalKind.OPERATIONAL,
        )

        assert policy.retrieval_kind is RetrievalKind.OPERATIONAL

    def test_valid_non_retrieval_policy(self) -> None:
        policy = IntentDecisionPolicy(
            intent=IntentType.UNKNOWN,
            default_decision=DecisionType.ASK_CLARIFICATION,
            reason_code=DecisionReasonCode.UNKNOWN_INTENT,
        )

        assert policy.retrieval_kind is None

    def test_wrong_intent_type_raises_type_error(self) -> None:
        with pytest.raises(
            TypeError,
            match="intent must be an IntentType instance",
        ):
            IntentDecisionPolicy(
                intent="refund_request",  # type: ignore[arg-type]
                default_decision=DecisionType.RETRIEVE_INFORMATION,
                reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
                retrieval_kind=RetrievalKind.KNOWLEDGE,
            )

    def test_wrong_decision_type_raises_type_error(self) -> None:
        with pytest.raises(
            TypeError,
            match="default_decision must be a DecisionType instance",
        ):
            IntentDecisionPolicy(
                intent=IntentType.REFUND_REQUEST,
                default_decision="retrieve_information",  # type: ignore[arg-type]
                reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
                retrieval_kind=RetrievalKind.KNOWLEDGE,
            )

    def test_wrong_reason_code_type_raises_type_error(self) -> None:
        with pytest.raises(
            TypeError,
            match="reason_code must be a DecisionReasonCode instance",
        ):
            IntentDecisionPolicy(
                intent=IntentType.REFUND_REQUEST,
                default_decision=DecisionType.RETRIEVE_INFORMATION,
                reason_code="policy_retrieval_required",  # type: ignore[arg-type]
                retrieval_kind=RetrievalKind.KNOWLEDGE,
            )

    def test_wrong_retrieval_kind_type_raises_type_error(self) -> None:
        with pytest.raises(
            TypeError,
            match="retrieval_kind must be a RetrievalKind instance or None",
        ):
            IntentDecisionPolicy(
                intent=IntentType.REFUND_REQUEST,
                default_decision=DecisionType.RETRIEVE_INFORMATION,
                reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
                retrieval_kind="knowledge",  # type: ignore[arg-type]
            )

    def test_wrong_actionable_type_raises_type_error(self) -> None:
        with pytest.raises(
            TypeError,
            match="potentially_actionable must be a boolean",
        ):
            IntentDecisionPolicy(
                intent=IntentType.REFUND_REQUEST,
                default_decision=DecisionType.RETRIEVE_INFORMATION,
                reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
                retrieval_kind=RetrievalKind.KNOWLEDGE,
                potentially_actionable=1,  # type: ignore[arg-type]
            )

    def test_wrong_priority_type_raises_type_error(self) -> None:
        with pytest.raises(
            TypeError,
            match="default_priority must be a DecisionPriority instance",
        ):
            IntentDecisionPolicy(
                intent=IntentType.REFUND_REQUEST,
                default_decision=DecisionType.RETRIEVE_INFORMATION,
                reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
                retrieval_kind=RetrievalKind.KNOWLEDGE,
                default_priority="high",  # type: ignore[arg-type]
            )

    def test_retrieve_information_requires_retrieval_kind(self) -> None:
        with pytest.raises(
            ValueError,
            match="RETRIEVE_INFORMATION policy requires retrieval_kind",
        ):
            IntentDecisionPolicy(
                intent=IntentType.REFUND_REQUEST,
                default_decision=DecisionType.RETRIEVE_INFORMATION,
                reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
            )

    @pytest.mark.parametrize(
        "decision",
        [
            DecisionType.ANSWER,
            DecisionType.PERFORM_ACTION,
            DecisionType.ASK_CLARIFICATION,
            DecisionType.ESCALATE,
        ],
    )
    def test_non_retrieval_decision_rejects_retrieval_kind(
        self,
        decision: DecisionType,
    ) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "retrieval_kind may only be populated when "
                "default_decision is RETRIEVE_INFORMATION"
            ),
        ):
            IntentDecisionPolicy(
                intent=IntentType.UNKNOWN,
                default_decision=decision,
                reason_code=DecisionReasonCode.UNKNOWN_INTENT,
                retrieval_kind=RetrievalKind.KNOWLEDGE,
            )

    def test_policy_is_immutable(self) -> None:
        policy = INTENT_DECISION_POLICIES[IntentType.REFUND_REQUEST]

        with pytest.raises(AttributeError):
            policy.potentially_actionable = False  # type: ignore[misc]


class TestRegistryStructure:
    def test_registry_is_mapping_proxy(self) -> None:
        assert isinstance(
            INTENT_DECISION_POLICIES,
            MappingProxyType,
        )

    def test_registry_cannot_be_mutated(self) -> None:
        with pytest.raises(TypeError):
            INTENT_DECISION_POLICIES[
                IntentType.REFUND_REQUEST
            ] = INTENT_DECISION_POLICIES[
                IntentType.REFUND_REQUEST
            ]  # type: ignore[index]

    def test_every_intent_has_exactly_one_policy(self) -> None:
        assert set(INTENT_DECISION_POLICIES) == set(IntentType)

    def test_policy_keys_match_policy_intents(self) -> None:
        for intent, policy in INTENT_DECISION_POLICIES.items():
            assert policy.intent is intent

    def test_all_registry_values_are_policies(self) -> None:
        assert all(
            isinstance(policy, IntentDecisionPolicy)
            for policy in INTENT_DECISION_POLICIES.values()
        )


class TestPolicyLookup:
    @pytest.mark.parametrize("intent", tuple(IntentType))
    def test_lookup_returns_registered_policy(
        self,
        intent: IntentType,
    ) -> None:
        result = get_intent_decision_policy(intent)

        assert result is INTENT_DECISION_POLICIES[intent]

    def test_lookup_rejects_non_intent(self) -> None:
        with pytest.raises(
            TypeError,
            match="intent must be IntentType",
        ):
            get_intent_decision_policy(
                "refund_request"  # type: ignore[arg-type]
            )


class TestDefaultRoutingPolicies:
    def test_refund_uses_knowledge_retrieval(self) -> None:
        policy = get_intent_decision_policy(
            IntentType.REFUND_REQUEST
        )

        assert (
            policy.default_decision
            is DecisionType.RETRIEVE_INFORMATION
        )
        assert policy.retrieval_kind is RetrievalKind.KNOWLEDGE
        assert (
            policy.reason_code
            is DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED
        )

    def test_order_status_uses_operational_retrieval(self) -> None:
        policy = get_intent_decision_policy(
            IntentType.ORDER_STATUS
        )

        assert (
            policy.default_decision
            is DecisionType.RETRIEVE_INFORMATION
        )
        assert policy.retrieval_kind is RetrievalKind.OPERATIONAL
        assert (
            policy.reason_code
            is DecisionReasonCode.OPERATIONAL_LOOKUP_REQUIRED
        )

    def test_general_question_uses_knowledge_retrieval(self) -> None:
        policy = get_intent_decision_policy(
            IntentType.GENERAL_QUESTION
        )

        assert (
            policy.default_decision
            is DecisionType.RETRIEVE_INFORMATION
        )
        assert policy.retrieval_kind is RetrievalKind.KNOWLEDGE
        assert policy.potentially_actionable is False

    def test_unknown_defaults_to_clarification(self) -> None:
        policy = get_intent_decision_policy(
            IntentType.UNKNOWN
        )

        assert (
            policy.default_decision
            is DecisionType.ASK_CLARIFICATION
        )
        assert policy.retrieval_kind is None
        assert policy.potentially_actionable is False
        assert (
            policy.reason_code
            is DecisionReasonCode.UNKNOWN_INTENT
        )

    def test_account_issue_defaults_to_high_priority(self) -> None:
        policy = get_intent_decision_policy(
            IntentType.ACCOUNT_ISSUE
        )

        assert (
            policy.default_priority
            is DecisionPriority.HIGH
        )
        
    def test_privacy_security_defaults_to_high_priority(self) -> None:
        policy = get_intent_decision_policy(
            IntentType.PRIVACY_SECURITY
        )

        assert (
            policy.default_priority
            is DecisionPriority.HIGH
        )

    @pytest.mark.parametrize(
        "intent",
        [
            intent
            for intent in IntentType
            if intent
            not in {
                IntentType.ACCOUNT_ISSUE,
                IntentType.PRIVACY_SECURITY,
            }
        ],
    )
    def test_other_intents_default_to_normal_priority(
        self,
        intent: IntentType,
    ) -> None:
        assert (
            INTENT_DECISION_POLICIES[intent].default_priority
            is DecisionPriority.NORMAL
        )


class TestDerivedPolicySets:
    def test_knowledge_retrieval_intents_are_derived_from_registry(
        self,
    ) -> None:
        expected = frozenset(
            intent
            for intent, policy in INTENT_DECISION_POLICIES.items()
            if (
                policy.default_decision
                is DecisionType.RETRIEVE_INFORMATION
                and policy.retrieval_kind
                is RetrievalKind.KNOWLEDGE
            )
        )

        assert get_knowledge_retrieval_intents() == expected

    def test_operational_retrieval_intents_are_derived_from_registry(
        self,
    ) -> None:
        expected = frozenset(
            intent
            for intent, policy in INTENT_DECISION_POLICIES.items()
            if (
                policy.default_decision
                is DecisionType.RETRIEVE_INFORMATION
                and policy.retrieval_kind
                is RetrievalKind.OPERATIONAL
            )
        )

        assert get_operational_retrieval_intents() == expected

    def test_actionable_intents_are_derived_from_registry(
        self,
    ) -> None:
        expected = frozenset(
            intent
            for intent, policy in INTENT_DECISION_POLICIES.items()
            if policy.potentially_actionable
        )

        assert get_actionable_intents() == expected

    def test_order_status_is_operational_not_knowledge(self) -> None:
        assert (
            IntentType.ORDER_STATUS
            in get_operational_retrieval_intents()
        )
        assert (
            IntentType.ORDER_STATUS
            not in get_knowledge_retrieval_intents()
        )

    def test_unknown_is_not_retrievable(self) -> None:
        assert (
            IntentType.UNKNOWN
            not in get_knowledge_retrieval_intents()
        )
        assert (
            IntentType.UNKNOWN
            not in get_operational_retrieval_intents()
        )

    def test_unknown_is_not_actionable(self) -> None:
        assert IntentType.UNKNOWN not in get_actionable_intents()


class TestRegistryValidation:
    def test_current_registry_is_valid(self) -> None:
        validate_intent_decision_policies()

    def test_validation_detects_missing_policy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        incomplete = {
            intent: policy
            for intent, policy in INTENT_DECISION_POLICIES.items()
            if intent is not IntentType.REFUND_REQUEST
        }

        monkeypatch.setattr(
            policies_module,
            "INTENT_DECISION_POLICIES",
            incomplete,
        )

        with pytest.raises(
            RuntimeError,
            match="Missing policies",
        ):
            validate_intent_decision_policies()

    def test_validation_detects_unexpected_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        invalid_registry = dict(
            INTENT_DECISION_POLICIES
        )
        invalid_registry["fake_intent"] = (
            INTENT_DECISION_POLICIES[
                IntentType.UNKNOWN
            ]
        )

        monkeypatch.setattr(
            policies_module,
            "INTENT_DECISION_POLICIES",
            invalid_registry,
        )

        with pytest.raises(
            RuntimeError,
            match="Unexpected policies",
        ):
            validate_intent_decision_policies()

    def test_validation_detects_wrong_policy_value_type(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        invalid_registry = dict(
            INTENT_DECISION_POLICIES
        )
        invalid_registry[IntentType.REFUND_REQUEST] = object()

        monkeypatch.setattr(
            policies_module,
            "INTENT_DECISION_POLICIES",
            invalid_registry,
        )

        with pytest.raises(
            RuntimeError,
            match="is not an IntentDecisionPolicy",
        ):
            validate_intent_decision_policies()

    def test_validation_detects_policy_key_mismatch(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = INTENT_DECISION_POLICIES[
            IntentType.REFUND_REQUEST
        ]

        mismatched_policy = replace(
            original,
            intent=IntentType.PAYMENT_ISSUE,
        )

        invalid_registry = dict(
            INTENT_DECISION_POLICIES
        )
        invalid_registry[
            IntentType.REFUND_REQUEST
        ] = mismatched_policy

        monkeypatch.setattr(
            policies_module,
            "INTENT_DECISION_POLICIES",
            invalid_registry,
        )

        with pytest.raises(
            RuntimeError,
            match="policy/key mismatch",
        ):
            validate_intent_decision_policies()
            
@pytest.mark.parametrize(
    ("intent", "expected_kind"),
    [
        (IntentType.REFUND_REQUEST, RetrievalKind.KNOWLEDGE),
        (IntentType.PAYMENT_ISSUE, RetrievalKind.KNOWLEDGE),
        (IntentType.ORDER_STATUS, RetrievalKind.OPERATIONAL),
        (IntentType.SHIPPING_ISSUE, RetrievalKind.KNOWLEDGE),
        (IntentType.CANCELLATION, RetrievalKind.KNOWLEDGE),
        (IntentType.SUBSCRIPTION_ISSUE, RetrievalKind.KNOWLEDGE),
        (IntentType.ACCOUNT_ISSUE, RetrievalKind.KNOWLEDGE),
        (IntentType.RETURN_EXCHANGE, RetrievalKind.KNOWLEDGE),
        (IntentType.PRIVACY_SECURITY, RetrievalKind.KNOWLEDGE),
        (IntentType.GENERAL_QUESTION, RetrievalKind.KNOWLEDGE),
    ],
)
def test_retrieval_routing(
    intent: IntentType,
    expected_kind: RetrievalKind,
) -> None:
    policy = get_intent_decision_policy(intent)

    assert (
        policy.default_decision
        is DecisionType.RETRIEVE_INFORMATION
    )
    assert policy.retrieval_kind is expected_kind