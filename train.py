"""Rebuild the published tables of `outputs/v1/` from the MEPS data (ML Zoomcamp entry point).

Needs the downloaded data, the DuckDB database and the dbt build (see the README). Run with
`uv run python train.py`. It fits the 2022 model, applies the monotone adult age rule and writes
`outputs/v1/`, then saves the OpenAPI schema of the service.
"""

from health_pricing import publish
from health_pricing.service import openapi


def main() -> None:
    directory = publish.publish()
    print(f"Rebuilt {directory}")
    openapi.PATH.write_text(openapi.schema_text(), encoding="utf-8")
    print(f"Saved {openapi.PATH}")


if __name__ == "__main__":
    main()
