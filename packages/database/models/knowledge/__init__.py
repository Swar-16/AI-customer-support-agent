# AI-customer-support-agent\packages\database\models\knowledge\__init__.py
from packages.database.models.knowledge.document import KnowledgeDocumentModel
from packages.database.models.knowledge.document_version import KnowledgeDocumentVersionModel
from packages.database.models.knowledge.chunk import KnowledgeChunkModel
from packages.database.models.knowledge.chunk_embedding import KnowledgeChunkEmbeddingModel
from packages.database.models.knowledge.document_version import KnowledgeDocumentVersionModel

__all__ = [
    "KnowledgeDocumentModel",
    "KnowledgeDocumentVersionModel",
    "KnowledgeChunkModel",
    "KnowledgeChunkEmbeddingModel",
    "KnowledgeDocumentVersionModel",
]