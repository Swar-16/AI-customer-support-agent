from __future__ import annotations
import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import Inspector

from packages.config.settings import get_settings

CONTRACT_FORMAT_VERSION = 1
DEFAULT_SCHEMAS: tuple[str, ...] = ("ai", "audit", "config", "knowledge", "support",)
DEFAULT_OUTPUT_PATH = Path("contracts/database_schema.json")

class DatabaseSchemaExportError(RuntimeError):
    """Raised when the database schema contract cannot be exported."""

def _json_safe(value: Any) -> Any:
    """Convert SQLAlchemy/PostgreSQL inspection values into deterministic JSON-compatible values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
        }

    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]

    return str(value)

def _sorted_records(records: Sequence[Mapping[str, Any]], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    normalized = [{str(key): _json_safe(value) for key, value in record.items()} for record in records]

    return sorted(normalized, key=lambda record: tuple(str(record.get(key) or "") for key in keys))

def _column_contract(column: Mapping[str, Any]) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "name": str(column["name"]),
        "type": str(column["type"]),
        "nullable": bool(column.get("nullable", True)),
        "default": _json_safe(column.get("default")),
        "comment": _json_safe(column.get("comment")),
    }

    if column.get("autoincrement") is not None:
        contract["autoincrement"] = _json_safe(column["autoincrement"])

    if column.get("identity") is not None:
        contract["identity"] = _json_safe(column["identity"])

    if column.get("computed") is not None:
        contract["computed"] = _json_safe(column["computed"])

    return contract

def _table_comment(inspector: Inspector, *, schema: str, table_name: str) -> str | None:
    try:
        result = inspector.get_table_comment(table_name, schema=schema)
        
    except NotImplementedError:
        return None

    comment = result.get("text")
    return str(comment) if comment is not None else None

def _table_contract(inspector: Inspector, *, schema: str, table_name: str, 
                    trigger_map: Mapping[tuple[str, str], list[dict[str, Any]]], policy_map: Mapping[tuple[str, str], list[dict[str, Any]]]
) -> dict[str, Any]:
    columns = [_column_contract(column) for column in inspector.get_columns(table_name, schema=schema)]
    primary_key = _json_safe(inspector.get_pk_constraint(table_name, schema=schema))
    foreign_keys = _sorted_records(inspector.get_foreign_keys(table_name, schema=schema), keys=("name", "referred_schema", "referred_table",))
    unique_constraints = _sorted_records(inspector.get_unique_constraints(table_name, schema=schema), keys=("name",))
    check_constraints = _sorted_records(inspector.get_check_constraints(table_name, schema=schema), keys=("name", "sqltext"))
    indexes = _sorted_records(inspector.get_indexes(table_name, schema=schema), keys=("name",))

    return {
        "name": table_name,
        "comment": _table_comment(inspector, schema=schema, table_name=table_name),
        "columns": columns,
        "primary_key": primary_key,
        "foreign_keys": foreign_keys,
        "unique_constraints": unique_constraints,
        "check_constraints": check_constraints,
        "indexes": indexes,
        "triggers": trigger_map.get((schema, table_name), []),
        "row_level_security_policies": policy_map.get((schema, table_name), []),
    }

def _load_triggers(engine: Engine, *, schemas: tuple[str, ...]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    statement = text(
        """
        SELECT
            namespace.nspname AS schema_name,
            relation.relname AS table_name,
            trigger.tgname AS trigger_name,
            pg_get_triggerdef(trigger.oid, true) AS definition,
            trigger.tgenabled AS enabled_state
        FROM pg_trigger AS trigger
        JOIN pg_class AS relation
          ON relation.oid = trigger.tgrelid
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE NOT trigger.tgisinternal
          AND namespace.nspname = ANY(CAST(:schemas AS text[]))
        ORDER BY
            namespace.nspname,
            relation.relname,
            trigger.tgname
        """
    )
    
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}

    with engine.connect() as connection:
        rows = connection.execute(statement, {"schemas": list(schemas)}).mappings()

        for row in rows:
            key = (str(row["schema_name"]), str(row["table_name"]),)
            result.setdefault(key, []).append(
                {
                    "name": str(row["trigger_name"]),
                    "definition": str(row["definition"]),
                    "enabled_state": str(row["enabled_state"]),
                }
            )

    return result

def _load_rls_policies(engine: Engine, *, schemas: tuple[str, ...]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    statement = text(
        """
        SELECT
            schemaname AS schema_name,
            tablename AS table_name,
            policyname AS policy_name,
            permissive,
            roles,
            cmd,
            qual,
            with_check
        FROM pg_policies
        WHERE schemaname = ANY(CAST(:schemas AS text[]))
        ORDER BY
            schemaname,
            tablename,
            policyname
        """
    )

    result: dict[tuple[str, str], list[dict[str, Any]],] = {}

    with engine.connect() as connection:
        rows = connection.execute(statement, {"schemas": list(schemas)}).mappings()
        for row in rows:
            key = (str(row["schema_name"]), str(row["table_name"]))
            result.setdefault(key, []).append(
                {
                    "name": str(row["policy_name"]),
                    "permissive": str(row["permissive"]),
                    "roles": _json_safe(row["roles"]),
                    "command": str(row["cmd"]),
                    "using": _json_safe(row["qual"]),
                    "with_check": _json_safe(row["with_check"]),
                }
            )

    return result

def _schema_enums(inspector: Inspector, *, schema: str) -> list[dict[str, Any]]:
    get_enums = getattr(inspector, "get_enums", None)
    if get_enums is None:
        return []

    enums = get_enums(schema=schema)
    return _sorted_records(enums, keys=("name",))

def build_contract(engine: Engine, *, schemas: tuple[str, ...]) -> dict[str, Any]:
    inspector = inspect(engine)
    existing_schemas = set(inspector.get_schema_names())
    missing_schemas = sorted(set(schemas) - existing_schemas)
    if missing_schemas:
        missing = ", ".join(missing_schemas)
        raise DatabaseSchemaExportError(f"Required database schemas do not exist: {missing}")

    trigger_map = _load_triggers(engine, schemas=schemas)
    policy_map = _load_rls_policies(engine, schemas=schemas)
    schema_contracts: list[dict[str, Any]] = []

    for schema in schemas:
        table_names = sorted(inspector.get_table_names(schema=schema))
        tables = [
            _table_contract(
                inspector,
                schema=schema,
                table_name=table_name,
                trigger_map=trigger_map,
                policy_map=policy_map,
            )
            for table_name in table_names
        ]

        schema_contracts.append({"name": schema, "enums": _schema_enums(inspector, schema=schema), "tables": tables,})

    return {
        "format_version": CONTRACT_FORMAT_VERSION,
        "database": "postgresql",
        "schemas": schema_contracts,
    }

def _render_contract(contract: Mapping[str, Any]) -> str:
    return (json.dumps(contract, indent=2, sort_keys=False, ensure_ascii=False) + "\n")

def _write_contract(*, output_path: Path, rendered_contract: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered_contract, encoding="utf-8", newline="\n")

def _check_contract(*, output_path: Path, rendered_contract: str) -> bool:
    if not output_path.exists():
        print(f"Database schema contract is missing: {output_path}", file=sys.stderr)
        return False

    current = output_path.read_text(encoding="utf-8")
    if current != rendered_contract:
        print("Database schema contract is out of date. Regenerate it with:\n  python scripts/export_database_schema.py", file=sys.stderr)
        return False

    print(f"Database schema contract is current: {output_path}")
    return True

def _parse_schemas(value: str) -> tuple[str, ...]:
    schemas = tuple(item.strip() for item in value.split(",") if item.strip())
    if not schemas:
        raise argparse.ArgumentTypeError("At least one schema is required.")

    if len(set(schemas)) != len(schemas):
        raise argparse.ArgumentTypeError("Schema names must not contain duplicates.")

    return schemas

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a deterministic PostgreSQL schema contract for the application schemas.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Generated contract path. Default: contracts/database_schema.json")
    parser.add_argument("--schemas", type=_parse_schemas, default=DEFAULT_SCHEMAS, help="Comma-separated schemas. Default: ai,audit,config,knowledge,support")
    parser.add_argument("--check", action="store_true", help="Verify that the committed contract matches the current database without rewriting it.")

    return parser

def main() -> int:
    arguments = _build_parser().parse_args()
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)

    try:
        contract = build_contract(engine, schemas=tuple(arguments.schemas))
        rendered_contract = _render_contract(contract)
        if arguments.check:
            return 0 if _check_contract(output_path=arguments.output, rendered_contract=rendered_contract) else 1

        _write_contract(output_path=arguments.output, rendered_contract=rendered_contract)
        table_count = sum(len(schema["tables"]) for schema in contract["schemas"])
        print(f"Exported {table_count} tables across {len(contract['schemas'])} schemas to {arguments.output}")
        return 0

    except DatabaseSchemaExportError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    except Exception as exc:
        print(f"Database schema export failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    finally:
        engine.dispose()

if __name__ == "__main__":
    raise SystemExit(main())