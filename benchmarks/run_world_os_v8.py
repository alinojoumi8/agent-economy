"""CLI for the frozen World OS semantics-8 benchmark."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.world_os_v8 import run_standard


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        default=str(ROOT / "benchmarks" / "world-os-v8-standard.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "benchmarks" / "receipts" / "world-os-v8-standard.json"),
    )
    args = parser.parse_args()
    receipt = run_standard(args.manifest, args.output)
    print(json.dumps({
        "status": receipt["status"],
        "manifest_sha256": receipt["manifest_sha256"],
        "output": str(Path(args.output).resolve()),
    }, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
