# AI-customer-support-agent\scripts\create_openapi_json.py
import json
from pathlib import Path
from apps.api.app.main import create_api_app

app=create_api_app()
path=Path('contracts/openapi.json')
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True), encoding='utf-8')