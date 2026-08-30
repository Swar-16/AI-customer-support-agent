"""enforce single published knowledge version

Revision ID: de48e87a85a0
Revises: 1842440b0b73
Create Date: 2026-08-30 05:52:19.165863

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'de48e87a85a0'
down_revision: Union[str, Sequence[str], None] = '1842440b0b73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        op.f("uq_knowledge_document_versions_one_published"),
        "knowledge_document_versions",
        ["document_id"],
        unique=True,
        schema="knowledge",
        postgresql_where="status = 'published'",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("uq_knowledge_document_versions_one_published"),
        table_name="knowledge_document_versions",
        schema="knowledge",
    )
