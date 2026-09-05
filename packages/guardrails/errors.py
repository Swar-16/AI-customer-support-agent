# packages/guardrail/errors.py
from __future__ import annotations


class GuardrailError(Exception):
    """
    Base exception for guardrail-layer failures.

    Guardrail policy violations are NOT exceptions. They are represented by GuardrailResult.

    Exceptions here represent invalid usage or execution failures in the guardrail subsystem itself.
    """

class GuardrailConfigurationError(GuardrailError):
    """Raised when guardrail policies/evaluator are configured incorrectly."""

class GuardrailEvaluationError(GuardrailError):
    """Raised when guardrail evaluation cannot be completed due to an internal execution problem rather than a policy violation."""

class InvalidGuardrailContextError(GuardrailError):
    """Raised when the supplied guardrail context is structurally invalid."""