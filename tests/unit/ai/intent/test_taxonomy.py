"""
Unit tests for packages.ai.intent.taxonomy.

The taxonomy layer defines semantic customer intent only.

Routing, retrieval strategy, actionability, workflow priority,
authorization, and operational requirements belong to downstream
decision/workflow layers and must not be tested here.
"""

from __future__ import annotations

import dataclasses
from types import MappingProxyType

import pytest

import packages.ai.intent.taxonomy as taxonomy
from packages.ai.intent.taxonomy import (
    INTENT_DEFINITIONS,
    IntentDefinition,
    IntentType,
    get_intent_definition,
    validate_intent_definitions,
)


# ---------------------------------------------------------------------------
# Structural completeness
# ---------------------------------------------------------------------------


def test_taxonomy_is_complete() -> None:
    validate_intent_definitions()

    assert set(INTENT_DEFINITIONS) == set(IntentType)


def test_every_definition_key_matches_its_intent() -> None:
    for intent, definition in INTENT_DEFINITIONS.items():
        assert definition.intent is intent


def test_every_registry_value_is_intent_definition() -> None:
    assert all(
        isinstance(definition, IntentDefinition)
        for definition in INTENT_DEFINITIONS.values()
    )


@pytest.mark.parametrize("intent", tuple(IntentType))
def test_every_intent_has_semantic_definition(
    intent: IntentType,
) -> None:
    definition = INTENT_DEFINITIONS[intent]

    assert definition.description.strip()
    assert definition.examples
    assert all(
        example.strip()
        for example in definition.examples
    )


def test_intent_type_values_are_unique() -> None:
    values = [intent.value for intent in IntentType]

    assert len(values) == len(set(values))


def test_intent_type_values_are_lowercase_snake_case() -> None:
    for intent in IntentType:
        value = intent.value

        assert value == value.lower()
        assert value
        assert " " not in value
        assert "-" not in value

        parts = value.split("_")

        assert all(part.isalnum() for part in parts)
        assert all(part for part in parts)


# ---------------------------------------------------------------------------
# IntentDefinition construction
# ---------------------------------------------------------------------------


def test_intent_definition_normalizes_description() -> None:
    definition = IntentDefinition(
        intent=IntentType.GENERAL_QUESTION,
        description="  General   supported \n question. ",
        examples=("Example question",),
    )

    assert (
        definition.description
        == "General supported question."
    )


def test_intent_definition_normalizes_examples() -> None:
    definition = IntentDefinition(
        intent=IntentType.GENERAL_QUESTION,
        description="General question.",
        examples=(
            "  First   example ",
            "Second\nexample",
        ),
    )

    assert definition.examples == (
        "First example",
        "Second example",
    )


def test_intent_definition_deduplicates_examples() -> None:
    definition = IntentDefinition(
        intent=IntentType.GENERAL_QUESTION,
        description="General question.",
        examples=(
            "Same example",
            " Same   example ",
            "Another example",
        ),
    )

    assert definition.examples == (
        "Same example",
        "Another example",
    )


def test_intent_definition_rejects_non_intent() -> None:
    with pytest.raises(
        TypeError,
        match="intent must be an IntentType instance",
    ):
        IntentDefinition(
            intent="general_question",  # type: ignore[arg-type]
            description="General question.",
            examples=("Example",),
        )


def test_intent_definition_rejects_non_string_description() -> None:
    with pytest.raises(
        TypeError,
        match="description must be a string",
    ):
        IntentDefinition(
            intent=IntentType.GENERAL_QUESTION,
            description=123,  # type: ignore[arg-type]
            examples=("Example",),
        )


@pytest.mark.parametrize(
    "description",
    [
        "",
        " ",
        "\n\t",
    ],
)
def test_intent_definition_rejects_blank_description(
    description: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="description cannot be empty",
    ):
        IntentDefinition(
            intent=IntentType.GENERAL_QUESTION,
            description=description,
            examples=("Example",),
        )


def test_intent_definition_requires_tuple_examples() -> None:
    with pytest.raises(
        TypeError,
        match="examples must be a tuple",
    ):
        IntentDefinition(
            intent=IntentType.GENERAL_QUESTION,
            description="General question.",
            examples=["Example"],  # type: ignore[arg-type]
        )


def test_intent_definition_requires_at_least_one_example() -> None:
    with pytest.raises(
        ValueError,
        match="requires at least one example",
    ):
        IntentDefinition(
            intent=IntentType.GENERAL_QUESTION,
            description="General question.",
            examples=(),
        )


@pytest.mark.parametrize(
    "examples",
    [
        ("",),
        ("   ",),
        ("\n\t",),
    ],
)
def test_intent_definition_rejects_blank_examples(
    examples: tuple[str, ...],
) -> None:
    with pytest.raises(
        ValueError,
        match="examples cannot contain empty values",
    ):
        IntentDefinition(
            intent=IntentType.GENERAL_QUESTION,
            description="General question.",
            examples=examples,
        )


def test_intent_definition_rejects_non_string_example() -> None:
    with pytest.raises(
        TypeError,
        match="examples must contain only strings",
    ):
        IntentDefinition(
            intent=IntentType.GENERAL_QUESTION,
            description="General question.",
            examples=(
                "Valid",
                123,  # type: ignore[arg-type]
            ),
        )


# ---------------------------------------------------------------------------
# Public lookup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("intent", tuple(IntentType))
def test_get_intent_definition_returns_registered_definition(
    intent: IntentType,
) -> None:
    definition = get_intent_definition(intent)

    assert definition is INTENT_DEFINITIONS[intent]
    assert definition.intent is intent


@pytest.mark.parametrize(
    "bad_value",
    [
        "refund_request",
        42,
        None,
        object(),
    ],
)
def test_get_intent_definition_rejects_non_intent_type(
    bad_value: object,
) -> None:
    with pytest.raises(
        TypeError,
        match="intent must be IntentType",
    ):
        get_intent_definition(
            bad_value  # type: ignore[arg-type]
        )


def test_get_intent_definition_raises_when_definition_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = dict(INTENT_DEFINITIONS)
    incomplete.pop(IntentType.UNKNOWN)

    monkeypatch.setattr(
        taxonomy,
        "INTENT_DEFINITIONS",
        incomplete,
    )

    with pytest.raises(KeyError):
        taxonomy.get_intent_definition(
            IntentType.UNKNOWN
        )


# ---------------------------------------------------------------------------
# Registry validation
# ---------------------------------------------------------------------------


def test_validate_intent_definitions_passes_for_real_taxonomy() -> None:
    assert validate_intent_definitions() is None


def test_validate_intent_definitions_detects_missing_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = dict(INTENT_DEFINITIONS)
    incomplete.pop(IntentType.UNKNOWN)

    monkeypatch.setattr(
        taxonomy,
        "INTENT_DEFINITIONS",
        incomplete,
    )

    with pytest.raises(
        RuntimeError,
        match="Missing definitions",
    ):
        taxonomy.validate_intent_definitions()


def test_validate_intent_definitions_detects_unexpected_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = dict(INTENT_DEFINITIONS)

    invalid["not_a_real_intent"] = (
        INTENT_DEFINITIONS[IntentType.UNKNOWN]
    )  # type: ignore[index]

    monkeypatch.setattr(
        taxonomy,
        "INTENT_DEFINITIONS",
        invalid,
    )

    with pytest.raises(
        RuntimeError,
        match="Unexpected definitions",
    ):
        taxonomy.validate_intent_definitions()


def test_validate_intent_definitions_detects_wrong_value_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = dict(INTENT_DEFINITIONS)

    invalid[IntentType.REFUND_REQUEST] = object()

    monkeypatch.setattr(
        taxonomy,
        "INTENT_DEFINITIONS",
        invalid,
    )

    with pytest.raises(
        RuntimeError,
        match="is not an IntentDefinition",
    ):
        taxonomy.validate_intent_definitions()


def test_validate_intent_definitions_detects_key_definition_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = dict(INTENT_DEFINITIONS)

    mismatched = dataclasses.replace(
        INTENT_DEFINITIONS[IntentType.PAYMENT_ISSUE],
        intent=IntentType.REFUND_REQUEST,
    )

    invalid[IntentType.PAYMENT_ISSUE] = mismatched

    monkeypatch.setattr(
        taxonomy,
        "INTENT_DEFINITIONS",
        invalid,
    )

    with pytest.raises(
        RuntimeError,
        match="definition/key mismatch",
    ):
        taxonomy.validate_intent_definitions()


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_intent_definition_is_frozen() -> None:
    definition = INTENT_DEFINITIONS[
        IntentType.REFUND_REQUEST
    ]

    with pytest.raises(dataclasses.FrozenInstanceError):
        definition.description = (  # type: ignore[misc]
            "Modified description"
        )


def test_intent_definition_uses_slots() -> None:
    definition = INTENT_DEFINITIONS[
        IntentType.REFUND_REQUEST
    ]

    assert not hasattr(definition, "__dict__")


def test_intent_definitions_mapping_is_read_only() -> None:
    assert isinstance(
        INTENT_DEFINITIONS,
        MappingProxyType,
    )

    with pytest.raises(TypeError):
        INTENT_DEFINITIONS[
            IntentType.UNKNOWN
        ] = INTENT_DEFINITIONS[
            IntentType.REFUND_REQUEST
        ]  # type: ignore[index]


# ---------------------------------------------------------------------------
# Semantic-quality invariants
# ---------------------------------------------------------------------------


def test_examples_are_not_reused_across_intents() -> None:
    seen: dict[str, IntentType] = {}

    for intent, definition in INTENT_DEFINITIONS.items():
        for example in definition.examples:
            normalized = example.casefold()

            assert normalized not in seen, (
                f"Example {example!r} is shared by "
                f"{seen.get(normalized)} and {intent}"
            )

            seen[normalized] = intent


def test_return_exchange_has_its_own_semantic_definition() -> None:
    definition = get_intent_definition(
        IntentType.RETURN_EXCHANGE
    )

    assert definition.intent is IntentType.RETURN_EXCHANGE


def test_privacy_security_has_its_own_semantic_definition() -> None:
    definition = get_intent_definition(
        IntentType.PRIVACY_SECURITY
    )

    assert definition.intent is IntentType.PRIVACY_SECURITY


def test_unknown_remains_explicitly_defined() -> None:
    definition = get_intent_definition(
        IntentType.UNKNOWN
    )

    assert definition.intent is IntentType.UNKNOWN