"""add started llm call status

Revision ID: 53167f87b96c
Revises: b90f79768b86
Create Date: 2026-08-26 20:15:15.855772
"""

from typing import Sequence, Union

from alembic import op


revision: str = "53167f87b96c"
down_revision: Union[str, Sequence[str], None] = "b90f79768b86"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_llm_calls_valid_status"),
        "llm_calls",
        schema="ai",
        type_="check",
    )

    op.create_check_constraint(
        op.f("ck_llm_calls_valid_status"),
        "llm_calls",
        """
        status IN (
            'started',
            'success',
            'failed',
            'timeout'
        )
        """,
        schema="ai",
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE ai.llm_calls
        SET status = 'failed',
            error_code = COALESCE(
                error_code,
                'MIGRATION_DOWNGRADE'
            ),
            error_message = COALESCE(
                error_message,
                'Incomplete LLM call converted during schema downgrade.'
            )
        WHERE status = 'started'
        """
    )

    op.drop_constraint(
        op.f("ck_llm_calls_valid_status"),
        "llm_calls",
        schema="ai",
        type_="check",
    )

    op.create_check_constraint(
        op.f("ck_llm_calls_valid_status"),
        "llm_calls",
        """
        status IN (
            'success',
            'failed',
            'timeout'
        )
        """,
        schema="ai",
    )