# AI-customer-support-agent\scripts\export_openapi.py
"""Export the API contract or check it against the committed snapshot."""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPOSITORY_ROOT / "contracts" / "openapi.json"

def generate_contract() -> dict:
    # Support invocation through: python scripts/export_openapi.py
    root = str(REPOSITORY_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)

    from apps.api.app.main import create_api_app

    # Schema generation does not enter lifespan or invoke API endpoints.
    application = create_api_app()
    return application.openapi()

def serialize_contract(contract: dict) -> str:
    return json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"

def write_contract(contents: str) -> None:
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=CONTRACT_PATH.parent, prefix=".openapi-", suffix=".tmp", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(contents)

        os.replace(temporary_path, CONTRACT_PATH)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the committed contract differs from the current API.")
    arguments = parser.parse_args()
    generated = serialize_contract(generate_contract())

    if arguments.check:
        if not CONTRACT_PATH.is_file():
            print("Missing contracts/openapi.json. Run the exporter first.", file=sys.stderr)
            return 1

        try:
            committed = serialize_contract(json.loads(CONTRACT_PATH.read_text(encoding="utf-8")))
        except (ValueError, UnicodeError):
            print("contracts/openapi.json is not a valid JSON contract.", file=sys.stderr)
            return 1

        if committed != generated:
            print("OpenAPI drift detected. Run 'python scripts/export_openapi.py' and review the changes.", file=sys.stderr,)
            return 1

        print("OpenAPI contract matches the current API.")
        return 0

    write_contract(generated)
    print("Exported contracts/openapi.json.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())