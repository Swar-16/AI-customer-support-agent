# AI-customer-support-agent\packages\application\conversations\conversation_context.py
from __future__ import annotations
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from packages.database.models.support.message import MessageModel

_ALLOWED_CONTEXT_ROLES: Final[frozenset[str]] = frozenset({"customer", "assistant",})

@dataclass(frozen=True, slots=True)
class ConversationContextConfig:
    """
    Bounds for customer-visible conversation history supplied to AI stages.

    These limits constrain database reads, prompt size, provider cost, and accidental exposure of excessive historical content.
    """
    max_messages: int = 12
    max_characters: int = 8_000
    max_characters_per_message: int = 2_000

    def __post_init__(self) -> None:
        for field_name in ("max_messages", "max_characters", "max_characters_per_message",):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")

            if value <= 0:
                raise ValueError(f"{field_name} must be greater than zero")

        if self.max_characters_per_message > self.max_characters:
            raise ValueError("max_characters_per_message cannot exceed max_characters")

class ConversationContextBuilder:
    """
    Build bounded prior customer-visible conversation context.

    Security and privacy properties:

    - only customer and assistant messages are included;
    - message metadata is never included;
    - message IDs and database identifiers are never included;
    - internal telemetry, prompts, decisions, retrieval results, tickets, escalation records, and provider errors are never included;
    - recent messages are preferred when the character budget is exceeded;
    - content is serialized as JSON so message boundaries remain explicit;
    - customer content is treated as data by downstream prompt builders.

    The caller must pass only messages preceding the current triggering customer message.
    The current message is supplied separately to intent classification and response generation.
    """
    def __init__(self, *, config: ConversationContextConfig | None = None) -> None:
        if config is not None and not isinstance(config, ConversationContextConfig):
            raise TypeError("config must be a ConversationContextConfig instance or None")

        self._config = config if config is not None else ConversationContextConfig()

    @property
    def max_messages(self) -> int:
        """
        Maximum number of messages the repository should load.

        The repository query and context builder therefore share the same explicit history bound.
        """
        return self._config.max_messages

    def build(self, *, messages: Sequence[MessageModel]) -> str | None:
        if isinstance(messages, (str, bytes)):
            raise TypeError("messages must be a sequence of MessageModel instances")

        if not isinstance(messages, Sequence):
            raise TypeError("messages must be a sequence of MessageModel instances")

        validated_messages = tuple(self._validate_and_normalize(messages))

        if not validated_messages:
            return None

        # Repository results should already be chronological, but sorting here
        # makes the boundary deterministic and prevents caller ordering errors.
        chronological_messages = tuple(sorted(validated_messages, key=lambda item: item["sequence_number"]))

        # Select from newest to oldest so the most recent context is retained when the total character budget is reached.
        selected_reversed: list[dict[str, object]] = []

        for item in reversed(chronological_messages):
            proposed_reversed = [*selected_reversed, item,]
            proposed = list(reversed(proposed_reversed))
            serialized = self._serialize(proposed)
            if len(serialized) > self._config.max_characters:
                continue

            selected_reversed.append(item)

        if not selected_reversed:
            return None

        selected = list(reversed(selected_reversed))
        context = self._serialize(selected)
        if len(context) > self._config.max_characters:
            raise RuntimeError("Conversation context exceeded its configured bound")

        return context

    def _validate_and_normalize(self, messages: Sequence[MessageModel]):
        seen_sequence_numbers: set[int] = set()

        for index, message in enumerate(messages):
            if not isinstance(message, MessageModel):
                raise TypeError(f"messages must contain only MessageModel instances; item {index} is {type(message).__name__}")

            if message.role not in _ALLOWED_CONTEXT_ROLES:
                # Internal/system roles must never silently enter an LLM conversation context.
                continue

            sequence_number = message.sequence_number
            if isinstance(sequence_number, bool) or not isinstance(sequence_number, int) or sequence_number < 1:
                raise ValueError("Message sequence_number must be a positive integer")

            if sequence_number in seen_sequence_numbers:
                raise ValueError("Conversation context contains duplicate sequence numbers")

            seen_sequence_numbers.add(sequence_number)
            if not isinstance(message.content, str):
                raise TypeError("Message content must be a string")

            normalized_content = " ".join(message.content.split())
            if not normalized_content:
                continue

            bounded_content = self._truncate_content(normalized_content)

            yield {
                "sequence_number": sequence_number,
                "role": message.role,
                "content": bounded_content,
            }

    def _truncate_content(self, content: str) -> str:
        limit = self._config.max_characters_per_message

        if len(content) <= limit:
            return content

        # The marker is application-controlled and makes truncation explicit.
        marker = "... [truncated]"
        retained_length = max(1, limit - len(marker))

        return (content[:retained_length].rstrip() + marker)

    @staticmethod
    def _serialize(messages: list[dict[str, object]]) -> str:
        """
        Serialize deterministically.

        JSON escaping prevents customer-authored quotes, newlines, pseudo-role labels, XML-like delimiters,
        or prompt fragments from changing message boundaries.
        """
        return json.dumps(
            {"messages": messages,},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )