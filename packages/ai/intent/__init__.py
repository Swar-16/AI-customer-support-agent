# AI-customer-support-agent\packages\ai\intent\__init__.py
from packages.ai.intent.classifier import (
    IntentClassifier,
    IntentClassifierConfig,
)
from packages.ai.intent.jev_classifier import (
    JevIntentClassifier,
    extract_entities_from_text,
)
from packages.ai.intent.schemas import (
    IntentEntities,
    IntentResult,
)
from packages.ai.intent.taxonomy import (
    IntentDefinition,
    IntentType,
)

__all__ = [
    "IntentClassifier",
    "IntentClassifierConfig",
    "JevIntentClassifier",
    "extract_entities_from_text",
    "IntentDefinition",
    "IntentEntities",
    "IntentResult",
    "IntentType",
]