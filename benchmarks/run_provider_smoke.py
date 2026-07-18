"""Record the provider-readiness portion of the semantics-8 release gate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.provider_smoke import write_provider_receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", help="JSON evidence from a completed ten-tick run")
    parser.add_argument(
        "--build-identifier", default="world-os-semantics-8-schema-12")
    parser.add_argument(
        "--output",
        default=str(ROOT / "benchmarks" / "receipts" / "world-os-v8-provider-smoke.json"),
    )
    args = parser.parse_args()
    evidence = None
    if args.evidence:
        evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    receipt = write_provider_receipt(
        args.output,
        build_identifier=args.build_identifier,
        evidence=evidence,
    )
    print(json.dumps({
        "status": receipt["status"],
        "reason": receipt["reason"],
        "output": str(Path(args.output).resolve()),
    }, sort_keys=True))
    return 0 if receipt["status"] in {"passed", "unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
