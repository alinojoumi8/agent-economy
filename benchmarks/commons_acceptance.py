"""Fork-based live Agent Commons post/feed/read acceptance receipt."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from engine.store import Store, load_json
from run import DATA_DIR, fork_run
from world.loop import World


RECEIPT_SCHEMA = "agent-economy-commons-live-acceptance-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_checkpoint_path(source_spec: str, data_dir: Path) -> Path:
    source = Path(source_spec)
    if source.exists():
        return source
    if "@" not in source_spec:
        raise FileNotFoundError(f"checkpoint not found: {source_spec}")
    run_id, _, tick_text = source_spec.partition("@")
    parent_path = data_dir / f"{run_id}.db"
    parent = Store(str(parent_path), create=False, read_only=True)
    try:
        row = parent.query_one(
            "SELECT path FROM checkpoints WHERE tick<=? "
            "ORDER BY tick DESC,id DESC LIMIT 1",
            (int(tick_text),),
        )
    finally:
        parent.close()
    if row is None:
        raise FileNotFoundError(
            f"no checkpoint at or before tick {tick_text} for run {run_id}"
        )
    return Path(str(row["path"]))


def _table_count(store: Store, table: str) -> int:
    return int(store.scalar(f"SELECT COUNT(*) FROM {table}", default=0))


def run_commons_acceptance(
    source_spec: str,
    *,
    data_dir: Path = DATA_DIR,
    output_path: Path = Path(
        "benchmarks/receipts/commons-live-post-read.json"
    ),
    dashboard_base_url: str = "http://127.0.0.1:8001",
) -> dict[str, Any]:
    """Fork a source checkpoint and prove public delivery plus explicit read."""
    source_path = _source_checkpoint_path(source_spec, data_dir)
    source_hash_before = _sha256(source_path)
    fork_id = fork_run(source_spec, data_dir=data_dir)
    database = data_dir / f"{fork_id}.db"
    store = Store(str(database))
    config = load_json(store.get_meta()["config_json"], {})
    world = World(store, config)
    world.restore_prng_state()
    try:
        agents = store.query(
            "SELECT id,name FROM agents "
            "WHERE alive=1 AND kind='citizen' ORDER BY id LIMIT 2"
        )
        if len(agents) < 2:
            raise RuntimeError("Commons acceptance requires two living citizens")
        author_id = int(agents[0]["id"])
        reader_id = int(agents[1]["id"])
        before = {
            table: _table_count(store, table)
            for table in (
                "commons_entries",
                "commons_feed_impressions",
                "memories",
                "causal_links",
            )
        }

        marker = f"Commons release acceptance on fork {fork_id}."
        entry = world.commons.publish(author_id, body=marker)
        feed = world.commons.feed(reader_id, kind="chronological")
        delivered = next(
            item for item in feed["entries"]
            if int(item["id"]) == int(entry["id"])
        )
        first_read = world.commons.read(
            reader_id, int(delivered["impression_id"])
        )
        repeated_read = world.commons.read(
            reader_id, int(delivered["impression_id"])
        )
        projection = world.commons.public_overview(kind="chronological")
        after = {
            table: _table_count(store, table)
            for table in before
        }
        criteria = {
            "post_published": str(entry["status"]) == "published",
            "feed_impression_delivered": int(delivered["id"]) == int(entry["id"]),
            "explicit_read_recorded": (
                first_read["idempotent"] is False
                and first_read["memory_id"] is not None
            ),
            "repeat_read_idempotent": repeated_read["idempotent"] is True,
            "public_projection_contains_post": int(entry["id"]) in {
                int(item["id"]) for item in projection["feed"]["entries"]
            },
            "publish_event_recorded": bool(store.scalar(
                "SELECT COUNT(*) FROM events "
                "WHERE kind='commons_entry_published' "
                "AND json_extract(payload_json,'$.author_agent_id')=?",
                (author_id,), default=0,
            )),
            "read_event_recorded": bool(store.scalar(
                "SELECT COUNT(*) FROM events "
                "WHERE kind='commons_entry_read' "
                "AND json_extract(payload_json,'$.viewer_agent_id')=?",
                (reader_id,), default=0,
            )),
            "delivery_causal_link_recorded": bool(store.scalar(
                "SELECT COUNT(*) FROM causal_links "
                "WHERE source_kind='commons_entry' AND source_id=? "
                "AND target_kind='feed_impression' AND target_id=? "
                "AND relation='delivered' AND authority='engine'",
                (int(entry["id"]), int(delivered["impression_id"])),
                default=0,
            )),
            "read_causal_link_recorded": bool(store.scalar(
                "SELECT COUNT(*) FROM causal_links "
                "WHERE source_kind='feed_impression' AND source_id=? "
                "AND target_kind='memory' AND target_id=? "
                "AND relation='observed' AND authority='engine'",
                (
                    int(delivered["impression_id"]),
                    int(first_read["memory_id"]),
                ),
                default=0,
            )),
        }
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "status": "passed" if all(criteria.values()) else "failed",
            "source_spec": str(source_spec),
            "source_checkpoint": source_path.name,
            "source_checkpoint_sha256": source_hash_before,
            "source_mutated": _sha256(source_path) != source_hash_before,
            "fork_run_id": fork_id,
            "fork_tick": int(store.tick),
            "synthetic_operator_scenario": True,
            "paid_inference_used": False,
            "actors": {
                "author": {
                    "id": author_id,
                    "name": str(agents[0]["name"]),
                },
                "reader": {
                    "id": reader_id,
                    "name": str(agents[1]["name"]),
                },
            },
            "entry_id": int(entry["id"]),
            "impression_id": int(delivered["impression_id"]),
            "memory_id": int(first_read["memory_id"]),
            "feed_policy": feed["policy"],
            "candidate_set_hash": feed["candidate_set_hash"],
            "criteria": criteria,
            "row_deltas": {
                table: after[table] - before[table]
                for table in before
            },
            "dashboard_url": (
                f"{dashboard_base_url.rstrip('/')}/runs/{fork_id}/commons"
            ),
        }
        receipt["criteria"]["source_checkpoint_unchanged"] = not receipt[
            "source_mutated"
        ]
        receipt["status"] = (
            "passed" if all(receipt["criteria"].values()) else "failed"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return receipt
    finally:
        world.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the fork-based Commons live post/read acceptance"
    )
    parser.add_argument(
        "source",
        help="Checkpoint path or RUN_ID@TICK source specification",
    )
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/receipts/commons-live-post-read.json"),
    )
    parser.add_argument(
        "--dashboard-base-url",
        default="http://127.0.0.1:8001",
    )
    args = parser.parse_args()
    receipt = run_commons_acceptance(
        args.source,
        data_dir=args.data_dir,
        output_path=args.output,
        dashboard_base_url=args.dashboard_base_url,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
