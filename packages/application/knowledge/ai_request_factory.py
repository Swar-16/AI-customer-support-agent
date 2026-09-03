from __future__ import annotations
from collections.abc import Mapping

from packages.ai.intent.schemas import IntentEntities, IntentResult
from packages.application.knowledge.models import KnowledgeRetrievalRequest
from packages.knowledge.retrieval.models import RetrievalFilters


class AIKnowledgeRetrievalRequestFactory:
    """
    Translate AI semantic understanding into the application-level knowledge retrieval contract.

    Trust boundary
    --------------
    IntentResult entities originate from customer language / AI inference. They are therefore semantic retrieval hints only.

    RetrievalFilters originate from trusted application context and are preserved independently as hard retrieval constraints.
    """
    def create(self, *, customer_message: str, intent_result: IntentResult, trusted_filters: RetrievalFilters | None = None, conversation_context: str | None = None) -> KnowledgeRetrievalRequest:
        if not isinstance(intent_result, IntentResult):
            raise TypeError("intent_result must be an IntentResult instance.")

        filters = self._resolve_trusted_filters(trusted_filters)
        entity_hints = self._extract_entity_hints(intent_result.entities)

        return KnowledgeRetrievalRequest(
            customer_message=customer_message,
            intent_key=intent_result.intent.value,
            entities=entity_hints,
            filters=filters,
            conversation_context=conversation_context,
        )

    @staticmethod
    def _resolve_trusted_filters(trusted_filters: RetrievalFilters | None) -> RetrievalFilters:
        if trusted_filters is None:
            return RetrievalFilters()

        if not isinstance(trusted_filters, RetrievalFilters):
            raise TypeError("trusted_filters must be a RetrievalFilters instance or None.")

        return trusted_filters

    @staticmethod
    def _extract_entity_hints(entities: IntentEntities) -> Mapping[str, str]:
        """
        Flatten structured IntentEntities into retrieval-safe string hints.

        Known typed entity fields retain their canonical field names. Additional string attributes are included as semantic hints.

        Empty values are omitted.

        Attributes cannot override canonical typed entities. This prevents ambiguous or future extension data from replacing stronger, schema-defined semantic information.
        """
        if not isinstance(entities, IntentEntities):
            raise TypeError("intent_result.entities must be an IntentEntities instance.")

        hints: dict[str, str] = {}

        canonical_fields = ("order_id", "transaction_id", "subscription_id", "account_id", "issue_type",)
        for field_name in canonical_fields:
            value = getattr(entities, field_name)
            if value is None:
                continue

            normalized = value.strip()
            if normalized:
                hints[field_name] = normalized

        attributes = entities.attributes

        if not isinstance(attributes, Mapping):
            raise TypeError("intent_result.entities.attributes must be a mapping.")

        for key, value in attributes.items():
            # Attributes are extensibility hints, not trusted structure.
            # Ignore malformed auxiliary entries instead of making the entire retrieval request unavailable.
            if not isinstance(key, str) or not isinstance(value, str):
                continue

            normalized_key = key.strip()
            normalized_value = value.strip()
            if not normalized_key or not normalized_value:
                continue

            # Canonical schema-defined fields take precedence.
            if normalized_key in canonical_fields:
                continue

            hints[normalized_key] = normalized_value

        return hints