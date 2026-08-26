"""
Unit tests for packages/ai/decision/schemas.py i.e. DecisionResult (the canonical output of the deterministic
decision layer used by the AI customer-support agent).

Run with:
    pytest test_decision_result.py -v

Design notes
------------
- Tests are grouped by concern (construction, field-level validation,
  cross-field semantics, immutability, serialization) so a failure
  immediately tells you *which contract* broke.
- Parametrization is used for boundary/equivalence-class testing instead
  of writing near-duplicate test functions.
- We assert on `pydantic.ValidationError` and, where it matters for
  debuggability, on the specific field/message inside `exc.errors()`
  rather than just "it raised something".
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.ai.decision.schemas import DecisionReasonCode, DecisionResult, DecisionType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_kwargs(**overrides) -> dict:
    """A minimal, valid ANSWER payload, overridable per-test."""
    base = dict(
        decision=DecisionType.ANSWER,
        reason_code=DecisionReasonCode.DIRECT_INFORMATIONAL_RESPONSE,
        reason_summary="Answered directly from the FAQ.",
    )
    base.update(overrides)
    return base


def error_fields(exc_info: pytest.ExceptionInfo) -> set[str]:
    """Flatten the `loc` tuples from a ValidationError into field names."""
    return {".".join(str(p) for p in err["loc"]) for err in exc_info.value.errors()}


# ---------------------------------------------------------------------------
# Happy path: one representative case per decision type
# ---------------------------------------------------------------------------

class TestValidConstruction:
    def test_valid_answer(self):
        result = DecisionResult(
            decision=DecisionType.ANSWER,
            reason_code=DecisionReasonCode.DIRECT_INFORMATIONAL_RESPONSE,
            reason_summary="Answered directly from the FAQ.",
            confidence=0.95,
        )
        assert result.decision is DecisionType.ANSWER
        assert result.required_information == ()
        assert result.metadata == {}

    def test_valid_retrieve_information(self):
        result = DecisionResult(
            decision=DecisionType.RETRIEVE_INFORMATION,
            reason_code=DecisionReasonCode.POLICY_RETRIEVAL_REQUIRED,
            reason_summary="Needs the refund policy document.",
        )
        assert result.decision is DecisionType.RETRIEVE_INFORMATION
        assert result.required_information == ()

    def test_valid_ask_clarification(self):
        result = DecisionResult(
            decision=DecisionType.ASK_CLARIFICATION,
            reason_code=DecisionReasonCode.MISSING_REQUIRED_INFORMATION,
            reason_summary="Need the order id to proceed.",
            required_information=("order_id",),
        )
        assert result.required_information == ("order_id",)

    def test_valid_perform_action(self):
        result = DecisionResult(
            decision=DecisionType.PERFORM_ACTION,
            reason_code=DecisionReasonCode.ACTION_REQUEST_DETECTED,
            reason_summary="User asked to cancel their subscription.",
        )
        assert result.decision is DecisionType.PERFORM_ACTION

    def test_valid_escalate(self):
        result = DecisionResult(
            decision=DecisionType.ESCALATE,
            reason_code=DecisionReasonCode.HUMAN_APPROVAL_REQUIRED,
            reason_summary="Refund exceeds auto-approval threshold.",
            confidence=1.0,
        )
        assert result.decision is DecisionType.ESCALATE

    def test_confidence_is_optional_and_defaults_to_none(self):
        result = DecisionResult(**make_kwargs())
        assert result.confidence is None

    def test_metadata_defaults_to_empty_dict_and_accepts_values(self):
        result = DecisionResult(**make_kwargs(metadata={"trace_id": "abc-123"}))
        assert result.metadata == {"trace_id": "abc-123"}


# ---------------------------------------------------------------------------
# confidence: numeric bounds [0.0, 1.0]
# ---------------------------------------------------------------------------

class TestConfidenceBounds:
    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_confidence_within_bounds_accepted(self, value):
        result = DecisionResult(**make_kwargs(confidence=value))
        assert result.confidence == value

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(**make_kwargs(confidence=1.01))
        assert "confidence" in error_fields(exc_info)

    def test_confidence_below_zero_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(**make_kwargs(confidence=-0.01))
        assert "confidence" in error_fields(exc_info)

    @pytest.mark.parametrize("value", [10.0, -5.0, float("inf")])
    def test_confidence_grossly_out_of_range_rejected(self, value):
        with pytest.raises(ValidationError):
            DecisionResult(**make_kwargs(confidence=value))

    def test_confidence_wrong_type_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(**make_kwargs(confidence="high"))
        assert "confidence" in error_fields(exc_info)


# ---------------------------------------------------------------------------
# reason_summary: non-empty, whitespace-normalized, length-capped
# ---------------------------------------------------------------------------

class TestReasonSummary:
    def test_blank_reason_summary_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(**make_kwargs(reason_summary=""))
        assert "reason_summary" in error_fields(exc_info)

    def test_whitespace_only_reason_summary_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(**make_kwargs(reason_summary="   \n\t  "))
        assert "reason_summary" in error_fields(exc_info)

    def test_internal_whitespace_is_collapsed(self):
        result = DecisionResult(
            **make_kwargs(reason_summary="Answered   from\nthe    FAQ.")
        )
        assert result.reason_summary == "Answered from the FAQ."

    def test_leading_and_trailing_whitespace_is_stripped(self):
        result = DecisionResult(**make_kwargs(reason_summary="   trimmed.   "))
        assert result.reason_summary == "trimmed."

    def test_reason_summary_at_max_length_accepted(self):
        summary = "a" * 500
        result = DecisionResult(**make_kwargs(reason_summary=summary))
        assert len(result.reason_summary) == 500

    def test_reason_summary_over_max_length_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(**make_kwargs(reason_summary="a" * 501))
        assert "reason_summary" in error_fields(exc_info)

    def test_reason_summary_missing_rejected(self):
        kwargs = make_kwargs()
        kwargs.pop("reason_summary")
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(**kwargs)
        assert "reason_summary" in error_fields(exc_info)


# ---------------------------------------------------------------------------
# required_information: normalization + semantic coupling to ASK_CLARIFICATION
# ---------------------------------------------------------------------------

class TestRequiredInformation:
    def test_duplicate_required_information_is_deduplicated_preserving_order(self):
        result = DecisionResult(
            decision=DecisionType.ASK_CLARIFICATION,
            reason_code=DecisionReasonCode.MISSING_REQUIRED_INFORMATION,
            reason_summary="Need identifiers.",
            required_information=("order_id", "email", "order_id", "email"),
        )
        assert result.required_information == ("order_id", "email")

    def test_required_information_items_are_stripped(self):
        result = DecisionResult(
            decision=DecisionType.ASK_CLARIFICATION,
            reason_code=DecisionReasonCode.MISSING_REQUIRED_INFORMATION,
            reason_summary="Need identifiers.",
            required_information=("  order_id  ", "email"),
        )
        assert result.required_information == ("order_id", "email")

    def test_required_information_with_blank_entry_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=DecisionReasonCode.MISSING_REQUIRED_INFORMATION,
                reason_summary="Need identifiers.",
                required_information=("order_id", "   "),
            )
        assert "required_information" in error_fields(exc_info)

    def test_ask_clarification_without_required_information_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=DecisionReasonCode.MISSING_REQUIRED_INFORMATION,
                reason_summary="Need more info.",
            )
        assert "ASK_CLARIFICATION must identify required information" in str(
            exc_info.value
        )

    def test_ask_clarification_with_empty_tuple_rejected(self):
        with pytest.raises(ValidationError):
            DecisionResult(
                decision=DecisionType.ASK_CLARIFICATION,
                reason_code=DecisionReasonCode.MISSING_REQUIRED_INFORMATION,
                reason_summary="Need more info.",
                required_information=(),
            )

    @pytest.mark.parametrize(
        "decision",
        [
            DecisionType.ANSWER,
            DecisionType.RETRIEVE_INFORMATION,
            DecisionType.PERFORM_ACTION,
            DecisionType.ESCALATE,
        ],
    )
    def test_non_clarification_decision_with_required_information_rejected(
        self, decision
    ):
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(
                decision=decision,
                reason_code=DecisionReasonCode.UNKNOWN_INTENT,
                reason_summary="Some reason.",
                required_information=("order_id",),
            )
        assert "required_information may only be populated for ASK_CLARIFICATION" in str(
            exc_info.value
        )


# ---------------------------------------------------------------------------
# Enum-typed fields: only defined members are accepted
# ---------------------------------------------------------------------------

class TestEnumFields:
    def test_unknown_decision_value_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(**make_kwargs(decision="do_something_undefined"))
        assert "decision" in error_fields(exc_info)

    def test_unknown_reason_code_value_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(**make_kwargs(reason_code="not_a_real_code"))
        assert "reason_code" in error_fields(exc_info)

    def test_decision_accepts_plain_string_matching_enum_value(self):
        # StrEnum values should be constructible from their raw string form,
        # since routing layers will often deserialize from JSON.
        result = DecisionResult(**make_kwargs(decision="answer"))
        assert result.decision is DecisionType.ANSWER


# ---------------------------------------------------------------------------
# Strictness: no undeclared fields, no mutation after construction
# ---------------------------------------------------------------------------

class TestModelStrictness:
    def test_unknown_extra_field_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            DecisionResult(**make_kwargs(unexpected_field="surprise"))
        assert "unexpected_field" in error_fields(exc_info)

    def test_model_is_frozen(self):
        result = DecisionResult(**make_kwargs())
        with pytest.raises(ValidationError):
            result.reason_summary = "mutated after construction"

    def test_model_copy_with_update_can_produce_a_new_instance(self):
        # Frozen models are still safely "updatable" via model_copy;
        # this documents the intended way to derive a modified result.
        original = DecisionResult(**make_kwargs())
        updated = original.model_copy(update={"reason_summary": "A new reason."})
        assert original.reason_summary == "Answered directly from the FAQ."
        assert updated.reason_summary == "A new reason."


# ---------------------------------------------------------------------------
# Serialization round-trip (contract that downstream consumers rely on)
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_model_dump_round_trip(self):
        original = DecisionResult(
            decision=DecisionType.ASK_CLARIFICATION,
            reason_code=DecisionReasonCode.MISSING_REQUIRED_INFORMATION,
            reason_summary="Need the order id.",
            required_information=("order_id",),
            confidence=0.4,
            metadata={"turn": 3},
        )
        dumped = original.model_dump(mode="json")
        rebuilt = DecisionResult(**dumped)
        assert rebuilt == original

    def test_model_dump_json_produces_plain_string_enum_values(self):
        result = DecisionResult(**make_kwargs())
        dumped = result.model_dump(mode="json")
        assert dumped["decision"] == "answer"
        assert dumped["reason_code"] == "direct_informational_response"