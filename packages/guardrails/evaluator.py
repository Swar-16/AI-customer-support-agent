# packages/guardrails/evaluator.py
from __future__ import annotations
from collections.abc import Iterable

from packages.guardrails.models import GuardrailContext, GuardrailOutcome, GuardrailReasonCode, GuardrailResult
from packages.guardrails.policies import DecisionCompatibilityPolicy, GuardrailPolicy, ResponsePresencePolicy, SensitiveActionClaimPolicy, UnsupportedOperationalClaimPolicy


class GuardrailEvaluator:
    """
    Deterministic coordinator for response guardrail policies.

    The evaluator deliberately contains no policy-specific business logic. Individual policies are responsible for detecting violations.

    Evaluation semantics:
        1. Policies execute in configured order.
        2. The first detected violation terminates evaluation.
        3. If no policy detects a violation, the response passes.

    Policy ordering is significant. Structural pipeline invariants should generally run before semantic defense-in-depth checks.
    """
    def __init__(self, policies: Iterable[GuardrailPolicy] | None = None) -> None:
        configured_policies = (tuple(policies) if policies is not None else self._default_policies())

        if not configured_policies:
            raise ValueError("GuardrailEvaluator requires at least one policy")

        for index, policy in enumerate(configured_policies):
            if not isinstance(policy, GuardrailPolicy):
                raise TypeError(f"GuardrailEvaluator policies must implement GuardrailPolicy; item {index} is {type(policy).__name__}")

        policy_ids = [policy.policy_id for policy in configured_policies]

        if len(policy_ids) != len(set(policy_ids)):
            raise ValueError("Guardrail policy IDs must be unique")

        self._policies = configured_policies

    @staticmethod
    def _default_policies() -> tuple[GuardrailPolicy, ...]:
        """
        Default V1 policy ordering.

        Structural checks run first because there is little value in applying semantic response checks to an invalid pipeline state.
        """
        return (
            ResponsePresencePolicy(),
            DecisionCompatibilityPolicy(),
            SensitiveActionClaimPolicy(),
            UnsupportedOperationalClaimPolicy(),
        )

    @property
    def policies(self) -> tuple[GuardrailPolicy, ...]:
        return self._policies

    def evaluate(self, context: GuardrailContext) -> GuardrailResult:
        """
        Evaluate the proposed response against all configured policies.

        Returns the first violation, or PASS when every policy accepts the response.
        """
        if not isinstance(context, GuardrailContext):
            raise TypeError("GuardrailEvaluator.evaluate() expects a GuardrailContext")

        for policy in self._policies:
            result = policy.evaluate(context)
            if result is None:
                continue

            if not isinstance(result, GuardrailResult):
                raise TypeError(f"Guardrail policy {policy.policy_id!r} returned {type(result).__name__}; expected GuardrailResult or None")

            if result.outcome is GuardrailOutcome.PASS:
                raise ValueError(f"Guardrail policy {policy.policy_id!r} returned PASS directly. Policies must return None when no violation is detected.")

            return result

        return GuardrailResult(
            outcome=GuardrailOutcome.PASS,
            reason_code=GuardrailReasonCode.SAFE_RESPONSE,
            reason_summary="The generated response passed all configured deterministic guardrail policies.",
            policy_id=None,
            metadata={"policies_evaluated": len(self._policies),},
        )