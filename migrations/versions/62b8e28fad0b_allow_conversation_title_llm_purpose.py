"""allow conversation title llm purpose

Revision ID: 62b8e28fad0b
Revises: 2c27647aaa28
Create Date: 2026-09-18 12:55:47.481729

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '62b8e28fad0b'
down_revision: Union[str, Sequence[str], None] = '2c27647aaa28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_llm_calls_valid_purpose"), "llm_calls", schema="ai", type_="check")
    op.create_check_constraint(
        op.f("ck_llm_calls_valid_purpose"),
        "llm_calls",
        """
        purpose IN (
            'intent_classification',
            'query_rewrite',
            'answer_generation',
            'action_decision',
            'escalation_summary',
            'guardrail_validation',
            'conversation_summary',
            'conversation_title',
            'other'
        )
        """,
        schema="ai",
    )


def downgrade() -> None:
    # A downgrade cannot restore the former constraint while title telemetry
    # rows still exist. Removing those rows would destroy observability data,
    # so fail explicitly rather than silently deleting them.
    connection = op.get_bind()
    title_call_count = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM ai.llm_calls
            WHERE purpose = 'conversation_title'
            """
        )
    ).scalar_one()

    if title_call_count:
        raise RuntimeError(
            "Cannot downgrade while ai.llm_calls contains "
            "conversation_title telemetry."
        )

    op.drop_constraint(
        op.f("ck_llm_calls_valid_purpose"),
        "llm_calls",
        schema="ai",
        type_="check",
    )

    op.create_check_constraint(
        op.f("ck_llm_calls_valid_purpose"),
        "llm_calls",
        """
        purpose IN (
            'intent_classification',
            'query_rewrite',
            'answer_generation',
            'action_decision',
            'escalation_summary',
            'guardrail_validation',
            'conversation_summary',
            'other'
        )
        """,
        schema="ai",
    )
