from __future__ import annotations
from enum import StrEnum

def enum_check_sql(column_name: str, enum_type: type[StrEnum]) -> str:
    """
    Build a SQL CHECK expression for a string-backed enum.

    Example:
        enum_check_sql("status", MyStatus)

    produces:
        status IN ('active', 'archived', ...)
    """
    values = ", ".join(f"'{member.value}'" for member in enum_type)

    return f"{column_name} IN ({values})"