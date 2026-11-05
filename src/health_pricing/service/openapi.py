"""Save the OpenAPI schema of the service to `_docs/openapi.json`.

Run `python -m health_pricing.service.openapi`. A test checks that the saved file is current.
"""

from __future__ import annotations

import json
from pathlib import Path

from health_pricing.service.app import app

PATH = Path(__file__).resolve().parents[3] / "_docs" / "openapi.json"


def schema_text() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    PATH.write_text(schema_text(), encoding="utf-8")
    print(PATH)
