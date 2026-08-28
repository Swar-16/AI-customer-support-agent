from __future__ import annotations
from enum import StrEnum

class KnowledgeDocumentStatus(StrEnum):
    """
    Lifecycle status of the logical knowledge document.

    A document is the stable business identity, such as:
        "Refund Policy"
        "Shipping FAQ"
        "Payment Support Guide"

    Individual revisions belong to KnowledgeDocumentVersion.
    """
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"

class KnowledgeVersionStatus(StrEnum):
    """
    Lifecycle status of a specific knowledge document version.

    Typical happy path:

        DRAFT -> PROCESSING -> READY -> PUBLISHED -> SUPERSEDED

    A processing failure transitions to FAILED.
    ARCHIVED represents a version intentionally removed from normal operational use while retaining it for audit/history.
    """
    DRAFT = "draft"
    PROCESSING = "processing"
    READY = "ready"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    ARCHIVED = "archived"


class KnowledgeSourceType(StrEnum):
    """
    Original source format of a knowledge version.

    This describes where the authoritative content came from.
    """
    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"
    PDF = "pdf"
    DOCX = "docx"
    HTML = "html"
    RICH_TEXT = "rich_text"


class KnowledgeContentType(StrEnum):
    """
    Broad semantic classification of knowledge.

    This should remain intentionally generic. It is metadata useful for
    organization and filtering, not a hard dependency of retrieval.
    """
    POLICY = "policy"
    FAQ = "faq"
    PROCEDURE = "procedure"
    GUIDE = "guide"
    REFERENCE = "reference"
    OTHER = "other"


class KnowledgeIngestionStatus(StrEnum):
    """
    Processing state of the ingestion pipeline for a document version.

    Version lifecycle and ingestion lifecycle are related but are not exactly the same concern,
    so keeping this vocabulary separate avoids overloading KnowledgeVersionStatus later.
    """
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class KnowledgeVisibility(StrEnum):
    """
    Controls who may use a knowledge document.

    This gives us room for internal agent-only material later without changing
    the core document model.
    """
    CUSTOMER = "customer"
    INTERNAL = "internal"
    BOTH = "both"