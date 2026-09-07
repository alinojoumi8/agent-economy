"""Start a declared continuation from an already verified, owned checkpoint copy."""
from __future__ import annotations

import json

from engine.store import Store
from world.loop import World
from world.shocks import SHOCK_KINDS, validate_shock_params, validate_shock_trigger


def validate_checkpoint_interventions(origin: dict, interventions: list[dict]) -> None:
    for item in interventions:
        if item.get("kind") not in SHOCK_KINDS or item.get("trigger", "shock") != "shock":
            raise ValueError("checkpoint study interventions need a known kind and explicit future tick")
        trigger = validate_shock_trigger("shock", item["trigger_params"])
        if trigger["tick"] <= origin["tick"]:
            raise ValueError("checkpoint intervention must follow the admitted boundary")
        duration = item.get("duration_ticks", 0)
        if type(duration) is not int or duration < 0:
            raise ValueError("checkpoint intervention duration must be a nonnegative integer")
        validate_shock_params(item["kind"], item.get("params", {}))


def open_checkpoint_branch(store: Store, config: dict, *, run_id: str,
                           origin: dict, interventions: list[dict],
                           replay: bool = False) -> World:
    """Preserve the inherited economy and append its declared future interventions.

    The caller owns this writable child. Source admission and exclusive copy
    publication happen before this function is called; it never opens a source.
    """
    meta = store.get_meta()
    if (meta["tick"] != origin["tick"] or meta["run_id"] != origin["run_id"]
            or meta["seed"] != origin["seed"] or config.get("seed") != origin["seed"]
            or meta["active_tick"] is not None or meta["next_phase"] not in (None, "NIGHT_CLOSE")
            or meta["status"] not in {"paused", "finished", "completed"}):
        raise ValueError("checkpoint branch does not match its admitted boundary")
    validate_checkpoint_interventions(origin, interventions)
    store.set_meta(run_id=run_id, parent_run_id=origin["run_id"], fork_tick=origin["tick"],
                   status="paused", config_json=json.dumps(config, sort_keys=True))
    world = World(store, config, replay=replay)
    try:
        world.restore_prng_state()
        world.status = "paused"
        for item in interventions:
            world.shocks.schedule(item["kind"], "shock", item["trigger_params"],
                duration_ticks=int(item.get("duration_ticks", 0)), params=item.get("params", {}),
                label=item.get("label", item["kind"]))
        store.log_event(origin["tick"], "research_checkpoint_branch", {
            "contract": "checkpoint-branch-v1", "origin_run_id": origin["run_id"],
            "origin_tick": origin["tick"], "origin_sha256": origin["database_sha256"],
            "initial_state_sha256": origin["initial_state_sha256"],
        }, phase="NIGHT_CLOSE", importance=2.0)
        store.commit()
        return world
    except BaseException:
        world.close()
        raise
