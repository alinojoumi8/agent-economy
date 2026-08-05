"""Generate the checked-in OpenAPI contract for the external-agent gateway."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.external_api import install_external_routes


def build_schema() -> dict:
    app = FastAPI(
        title="Agent Economy External Agent Gateway",
        version="2.0.0",
        description="Scoped REST, OAuth, and MCP boundary for owner-hosted agents.",
    )
    placeholder = SimpleNamespace(
        runtime=SimpleNamespace(external=None), commons=None)
    install_external_routes(app, placeholder, hosted_safe=False)
    return app.openapi()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="openapi/agent-economy-v2.json")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_schema(), indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
