# AI-customer-support-agent\packages\ai\intent\__init__.py
from packages.ai.intent.schemas import (
    IntentEntities,
    IntentResult,
)
from packages.ai.intent.taxonomy import (
    IntentDefinition,
    IntentType,
)

__all__ = [
    "IntentDefinition",
    "IntentEntities",
    "IntentResult",
    "IntentType",
]