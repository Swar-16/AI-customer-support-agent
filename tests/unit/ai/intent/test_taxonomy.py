"""
Unit tests for packages.ai.intent.taxonomy

Covers:
- Structural integrity of the taxonomy (completeness, consistency)
- Public accessor functions (get_intent_definition, get_all_intents,
  get_actionable_intents, get_retrieval_intents)
- validate_taxonomy() failure modes (via monkeypatching module state)
- Immutability guarantees (frozen dataclass, MappingProxyType)
- Domain-specific invariants (priorities, non-overlapping examples)
"""

from __future__ import annotations

import dataclasses

import pytest

import packages.ai.intent.taxonomy as taxonomy
from packages.ai.intent.taxonomy import (
    INTENT_DEFINITIONS,
    IntentDefinition,
    IntentType,
    get_actionable_intents,
    get_all_intents,
    get_intent_definition,
    get_retrieval_intents,
    validate_taxonomy,
)


# ---------------------------------------------------------------------------
# Structural completeness / consistency
# ---------------------------------------------------------------------------

def test_taxonomy_is_complete() -> None:
    validate_taxonomy()
    assert set(INTENT_DEFINITIONS) == set(IntentType)


def test_every_definition_key_matches_its_own_intent_field() -> None:
    for key, definition in INTENT_DEFINITIONS.items():
        assert key is definition.intent


@pytest.mark.parametrize("intent", list(IntentType))
def test_every_intent_has_required_metadata(intent: IntentType) -> None:
    definition = INTENT_DEFINITIONS[intent]
    assert definition.display_name.strip()
    assert definition.description.strip()
    assert len(definition.positive_examples) > 0
    assert all(example.strip() for example in definition.positive_examples)


def test_no_duplicate_display_names() -> None:
    names = [d.display_name for d in INTENT_DEFINITIONS.values()]
    assert len(names) == len(set(names))


def test_intent_type_values_are_lowercase_snake_case() -> None:
    for intent in IntentType:
        assert intent.value == intent.value.lower()
        assert " " not in intent.value


# ---------------------------------------------------------------------------
# get_all_intents
# ---------------------------------------------------------------------------

def test_get_all_intents_returns_every_member_in_declaration_order() -> None:
    assert get_all_intents() == tuple(IntentType)


def test_get_all_intents_returns_a_tuple() -> None:
    assert isinstance(get_all_intents(), tuple)


# ---------------------------------------------------------------------------
# get_intent_definition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("intent", list(IntentType))
def test_get_intent_definition_returns_matching_definition(intent: IntentType) -> None:
    definition = get_intent_definition(intent)
    assert definition is INTENT_DEFINITIONS[intent]
    assert definition.intent is intent


@pytest.mark.parametrize("bad_value", ["refund_request", 42, None, object()])
def test_get_intent_definition_rejects_non_intent_type(bad_value: object) -> None:
    with pytest.raises(TypeError):
        get_intent_definition(bad_value)  # type: ignore[arg-type]


def test_get_intent_definition_raises_key_error_when_metadata_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = {
        intent: definition
        for intent, definition in INTENT_DEFINITIONS.items()
        if intent is not IntentType.UNKNOWN
    }
    monkeypatch.setattr(taxonomy, "INTENT_DEFINITIONS", incomplete)
    with pytest.raises(KeyError):
        get_intent_definition(IntentType.UNKNOWN)


# ---------------------------------------------------------------------------
# get_actionable_intents / get_retrieval_intents
# ---------------------------------------------------------------------------

def test_actionable_intents_matches_flags_on_definitions() -> None:
    expected = frozenset(
        intent for intent, d in INTENT_DEFINITIONS.items() if d.potentially_actionable
    )
    assert get_actionable_intents() == expected


def test_retrieval_intents_matches_flags_on_definitions() -> None:
    expected = frozenset(
        intent for intent, d in INTENT_DEFINITIONS.items() if d.requires_policy_retrieval
    )
    assert get_retrieval_intents() == expected


def test_actionable_and_retrieval_return_frozensets() -> None:
    assert isinstance(get_actionable_intents(), frozenset)
    assert isinstance(get_retrieval_intents(), frozenset)


def test_unknown_is_not_actionable() -> None:
    assert IntentType.UNKNOWN not in get_actionable_intents()


def test_unknown_does_not_require_retrieval() -> None:
    assert IntentType.UNKNOWN not in get_retrieval_intents()


def test_general_question_requires_retrieval_but_is_not_actionable() -> None:
    assert IntentType.GENERAL_QUESTION in get_retrieval_intents()
    assert IntentType.GENERAL_QUESTION not in get_actionable_intents()


def test_refund_requires_retrieval() -> None:
    assert IntentType.REFUND_REQUEST in get_retrieval_intents()


def test_order_status_does_not_require_policy_retrieval_by_default() -> None:
    assert IntentType.ORDER_STATUS not in get_retrieval_intents()


def test_order_status_is_actionable() -> None:
    assert IntentType.ORDER_STATUS in get_actionable_intents()


# ---------------------------------------------------------------------------
# Priority defaults
# ---------------------------------------------------------------------------

def test_account_issue_has_high_priority() -> None:
    assert INTENT_DEFINITIONS[IntentType.ACCOUNT_ISSUE].default_priority == "high"


@pytest.mark.parametrize(
    "intent",
    [i for i in IntentType if i is not IntentType.ACCOUNT_ISSUE],
)
def test_other_intents_default_to_normal_priority(intent: IntentType) -> None:
    assert INTENT_DEFINITIONS[intent].default_priority == "normal"


# ---------------------------------------------------------------------------
# validate_taxonomy failure modes
# ---------------------------------------------------------------------------

def _definition_for(intent: IntentType, **overrides: object) -> IntentDefinition:
    base = INTENT_DEFINITIONS[intent]
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def test_validate_taxonomy_raises_when_definition_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = {
        intent: definition
        for intent, definition in INTENT_DEFINITIONS.items()
        if intent is not IntentType.UNKNOWN
    }
    monkeypatch.setattr(taxonomy, "INTENT_DEFINITIONS", incomplete)
    with pytest.raises(RuntimeError, match="Missing definitions"):
        validate_taxonomy()


def test_validate_taxonomy_detects_unexpected_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bogus_key = "not_a_real_intent"

    bloated = dict(INTENT_DEFINITIONS)
    bloated[bogus_key] = INTENT_DEFINITIONS[IntentType.UNKNOWN]  # type: ignore[index]

    monkeypatch.setattr(taxonomy, "INTENT_DEFINITIONS", bloated)

    with pytest.raises(
        RuntimeError,
        match="Unexpected definitions.*not_a_real_intent",
    ):
        validate_taxonomy()


def test_validate_taxonomy_raises_when_intent_field_mismatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mismatched = dict(INTENT_DEFINITIONS)
    mismatched[IntentType.REFUND_REQUEST] = _definition_for(
        IntentType.PAYMENT_ISSUE  # intent field points elsewhere than the dict key
    )
    monkeypatch.setattr(taxonomy, "INTENT_DEFINITIONS", mismatched)
    with pytest.raises(RuntimeError, match="mismatch"):
        validate_taxonomy()


def test_validate_taxonomy_raises_when_display_name_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = dict(INTENT_DEFINITIONS)
    broken[IntentType.REFUND_REQUEST] = _definition_for(
        IntentType.REFUND_REQUEST, display_name="   "
    )
    monkeypatch.setattr(taxonomy, "INTENT_DEFINITIONS", broken)
    with pytest.raises(RuntimeError, match="display name"):
        validate_taxonomy()


def test_validate_taxonomy_raises_when_description_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = dict(INTENT_DEFINITIONS)
    broken[IntentType.REFUND_REQUEST] = _definition_for(
        IntentType.REFUND_REQUEST, description=""
    )
    monkeypatch.setattr(taxonomy, "INTENT_DEFINITIONS", broken)
    with pytest.raises(RuntimeError, match="description"):
        validate_taxonomy()


def test_validate_taxonomy_raises_when_no_positive_examples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = dict(INTENT_DEFINITIONS)
    broken[IntentType.REFUND_REQUEST] = _definition_for(
        IntentType.REFUND_REQUEST, positive_examples=()
    )
    monkeypatch.setattr(taxonomy, "INTENT_DEFINITIONS", broken)
    with pytest.raises(RuntimeError, match="positive examples"):
        validate_taxonomy()


def test_validate_taxonomy_passes_on_unmodified_taxonomy() -> None:
    # Sanity check that validate_taxonomy() is a no-op / returns None on
    # the real, shipped taxonomy (also covered at import time).
    assert validate_taxonomy() is None


# ---------------------------------------------------------------------------
# Immutability guarantees
# ---------------------------------------------------------------------------

def test_intent_definition_is_frozen() -> None:
    definition = INTENT_DEFINITIONS[IntentType.REFUND_REQUEST]
    with pytest.raises(dataclasses.FrozenInstanceError):
        definition.display_name = "Something Else"  # type: ignore[misc]


def test_intent_definition_has_no_dict_due_to_slots() -> None:
    definition = INTENT_DEFINITIONS[IntentType.REFUND_REQUEST]
    assert not hasattr(definition, "__dict__")


def test_intent_definitions_mapping_is_read_only() -> None:
    with pytest.raises(TypeError):
        INTENT_DEFINITIONS[IntentType.UNKNOWN] = INTENT_DEFINITIONS[IntentType.REFUND_REQUEST]  # type: ignore[index]


# ---------------------------------------------------------------------------
# Domain design invariants (documented as "no overlapping intents")
# ---------------------------------------------------------------------------

def test_no_positive_example_is_reused_verbatim_across_different_intents() -> None:
    seen: dict[str, IntentType] = {}
    for intent, definition in INTENT_DEFINITIONS.items():
        for example in definition.positive_examples:
            assert example not in seen, (
                f"Example {example!r} appears as a positive example for both "
                f"{seen.get(example)} and {intent}"
            )
            seen[example] = intent


@pytest.mark.parametrize("intent", list(IntentType))
def test_negative_examples_do_not_appear_in_the_same_intents_positive_examples(
    intent: IntentType,
) -> None:
    definition = INTENT_DEFINITIONS[intent]
    assert set(definition.negative_examples).isdisjoint(definition.positive_examples)