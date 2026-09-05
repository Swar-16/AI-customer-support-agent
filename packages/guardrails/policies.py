# packages/guardrails/policies.py
from __future__ import annotations
from abc import ABC, abstractmethod
import re

from packages.ai.decision.schemas import DecisionType
from packages.guardrails.models import GuardrailContext, GuardrailOutcome, GuardrailReasonCode, GuardrailResult


class GuardrailPolicy(ABC):
    """
    Base contract for deterministic response guardrail policies.

    A policy returns:
        - GuardrailResult when it detects a violation;
        - None when it does not detect a violation.

    The evaluator is responsible for combining policies and producing the final PASS result.
    """
    policy_id: str

    @abstractmethod
    def evaluate(self, context: GuardrailContext) -> GuardrailResult | None:
        raise NotImplementedError

class ResponsePresencePolicy(GuardrailPolicy):
    """
    Ensure response-producing decisions actually have customer-visible text.

    At the moment, ANSWER and RETRIEVE_INFORMATION are expected to eventually produce a response before guardrail evaluation.

    Clarification/escalation/refusal/action paths may have separate response generation strategies later and therefore are not handled here.
    """
    policy_id = "response_presence"
    _RESPONSE_REQUIRED_DECISIONS = frozenset({DecisionType.ANSWER, DecisionType.RETRIEVE_INFORMATION,})

    def evaluate(self, context: GuardrailContext) -> GuardrailResult | None:
        if context.decision.decision not in self._RESPONSE_REQUIRED_DECISIONS:
            return None

        if context.generated_response is not None:
            return None

        return GuardrailResult(
            outcome=GuardrailOutcome.ESCALATE,
            reason_code=GuardrailReasonCode.MISSING_GENERATED_RESPONSE,
            reason_summary="The pipeline reached a response-producing decision without a generated customer response.",
            policy_id=self.policy_id,
        )

class DecisionCompatibilityPolicy(GuardrailPolicy):
    """
    Prevent a generated answer from being exposed for a workflow decision that should not produce a normal authoritative customer answer.

    This protects orchestration boundaries: generation must not silently override a deterministic escalation, refusal, or clarification decision.
    """
    policy_id = "decision_compatibility"
    _DIRECT_RESPONSE_DECISIONS = frozenset({DecisionType.ANSWER, DecisionType.RETRIEVE_INFORMATION,})

    def evaluate(self, context: GuardrailContext) -> GuardrailResult | None:
        if context.generated_response is None:
            return None

        if context.decision.decision in self._DIRECT_RESPONSE_DECISIONS:
            return None

        return GuardrailResult(
            outcome=GuardrailOutcome.ESCALATE,
            reason_code=GuardrailReasonCode.DECISION_RESPONSE_MISMATCH,
            reason_summary="A customer response was generated for a decision that does not permit a normal direct answer.",
            policy_id=self.policy_id,
            metadata={"decision": context.decision.decision.value,},
        )

class SensitiveActionClaimPolicy(GuardrailPolicy):
    """
    Defense-in-depth check preventing the language model from claiming that a sensitive business action was executed.

    The application currently has no trusted action-result contract in the guardrail context.
    Therefore any explicit claim that the assistant itself completed a sensitive action is unsafe.

    This is intentionally narrow. It is not intended to understand arbitrary natural language or replace the future action authorization subsystem.
    """
    policy_id = "sensitive_action_claim"
    _PATTERNS = (
        re.compile(
            r"\b(?:i|we|we've|i've)\s+"
            r"(?:have\s+)?"
            r"(?:issued|processed|completed|approved|initiated)\s+"
            r"(?:your\s+|the\s+)?refund\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:i|we|we've|i've)\s+"
            r"(?:have\s+)?"
            r"(?:cancelled|canceled)\s+"
            r"(?:your\s+|the\s+)?"
            r"(?:order|subscription|account)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:i|we|we've|i've)\s+"
            r"(?:have\s+)?"
            r"(?:changed|updated|reset)\s+"
            r"(?:your\s+|the\s+)?"
            r"(?:account|password|payment method|subscription)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:i|we|we've|i've)\s+"
            r"(?:have\s+)?"
            r"(?:reversed|voided)\s+"
            r"(?:your\s+|the\s+)?"
            r"(?:payment|charge|transaction)\b",
            re.IGNORECASE,
        ),
    )

    def evaluate(self, context: GuardrailContext) -> GuardrailResult | None:
        response = context.generated_response
        if response is None:
            return None

        for pattern in self._PATTERNS:
            if pattern.search(response) is None:
                continue

            return GuardrailResult(
                outcome=GuardrailOutcome.ESCALATE,
                reason_code=GuardrailReasonCode.SENSITIVE_ACTION_CLAIM,
                reason_summary="The generated response claims that a sensitive business action was completed without a trusted action result.",
                policy_id=self.policy_id,
            )

        return None

class UnsupportedOperationalClaimPolicy(GuardrailPolicy):
    """
    Prevent knowledge-grounded responses from presenting operational customer facts as though they were retrieved from a trusted operational system.

    This check is intentionally conservative.

    Operational facts include claims about the current state of a particular order, transaction, payment, shipment, subscription, or account.

    The full version of this policy should eventually use structured operational evidence rather than textual heuristics.
    """
    policy_id = "unsupported_operational_claim"
    _OPERATIONAL_FACT_PATTERNS = (
        re.compile(
            r"\byour\s+order\s+(?:is|has been|was)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\byour\s+(?:payment|transaction|charge)\s+"
            r"(?:is|has been|was)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\byour\s+(?:shipment|package)\s+"
            r"(?:is|has been|was)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\byour\s+subscription\s+"
            r"(?:is|has been|was)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\byour\s+account\s+"
            r"(?:is|has been|was)\b",
            re.IGNORECASE,
        ),
    )

    def evaluate(self, context: GuardrailContext) -> GuardrailResult | None:
        response = context.generated_response
        if response is None:
            return None

        has_operational_evidence = any(evidence.source_type.value == "operational" for evidence in context.retrieved_evidence)
        if has_operational_evidence:
            return None

        for pattern in self._OPERATIONAL_FACT_PATTERNS:
            if pattern.search(response) is None:
                continue

            return GuardrailResult(
                outcome=GuardrailOutcome.ESCALATE,
                reason_code=GuardrailReasonCode.UNSUPPORTED_OPERATIONAL_CLAIM,
                reason_summary="The generated response presents customer-specific operational information without trusted operational evidence.",
                policy_id=self.policy_id,
            )

        return None