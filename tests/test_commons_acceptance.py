from pathlib import Path

from benchmarks.commons_acceptance import run_commons_acceptance
from engine.store import Store
from run_config import load_config
from world.loop import World


def test_forked_commons_acceptance_preserves_source_and_writes_receipt(tmp_path):
    source_path = tmp_path / "source.db"
    config = load_config("runs/world-os-external.yaml")
    config["population"]["size"] = 4
    config["firms"]["count"] = 2
    config["firms"]["listed"] = 1
    config["banks"]["count"] = 1
    config["checkpoint_every"] = 0
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    source = Store(str(source_path))
    source.init_run_meta("commons-source", 42, config)
    world = World(source, config)
    world.initialize()
    world.close()

    output = tmp_path / "receipt.json"
    receipt = run_commons_acceptance(
        str(source_path),
        data_dir=tmp_path / "runs",
        output_path=output,
        dashboard_base_url="http://127.0.0.1:8123",
    )

    assert receipt["status"] == "passed"
    assert all(receipt["criteria"].values())
    assert receipt["source_mutated"] is False
    assert len(receipt["source_checkpoint_sha256"]) == 64
    assert receipt["synthetic_operator_scenario"] is True
    assert receipt["paid_inference_used"] is False
    assert receipt["row_deltas"]["commons_entries"] == 1
    assert receipt["row_deltas"]["commons_feed_impressions"] == 1
    assert receipt["row_deltas"]["memories"] == 1
    assert receipt["dashboard_url"].endswith(
        f"/runs/{receipt['fork_run_id']}/commons"
    )
    assert output.exists()

    source_check = Store(str(source_path), create=False, read_only=True)
    assert source_check.scalar(
        "SELECT COUNT(*) FROM commons_entries", default=0
    ) == 0
    source_check.close()

    fork_check = Store(
        str(tmp_path / "runs" / f"{receipt['fork_run_id']}.db"),
        create=False,
        read_only=True,
    )
    assert fork_check.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='commons_entry_read'",
        default=0,
    ) == 1
    fork_check.close()
