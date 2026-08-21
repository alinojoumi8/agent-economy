import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from communications.policy import Principal
from server.projections.cache import ProjectionSnapshotCache
from server.projections.snapshot import build_snapshot
from server.projections.transport import projection_delta_message
from server.v2_api import install_v2_routes


def _finalize_projection(store, tick: int) -> None:
    store.set_meta(
        tick=tick,
        status="paused",
        phase="FINALIZE",
        config_json=json.dumps({"engine_semantics_version": 8}),
    )
    store.execute(
        "INSERT INTO projection_commits (tick,phase,domains_json) "
        "VALUES (?,'FINALIZE','[\"summary\",\"events\"]')",
        (tick,),
    )
    store.commit()


def test_cache_reuses_exact_identity_and_returns_defensive_copies(store):
    _finalize_projection(store, 4)
    calls = 0

    def builder(current_store, _principal, *, as_of_tick, domains):
        nonlocal calls
        calls += 1
        return {
            "summary": {
                "status": str(current_store.get_meta()["status"]),
                "tick": as_of_tick,
                "domains": list(domains),
            }
        }

    cache = ProjectionSnapshotCache(max_entries=4, builder=builder)
    principal = Principal("ordinary-dashboard")

    first = cache.snapshot(
        store, principal, as_of_tick=4, domains=("summary",))
    first["summary"]["status"] = "mutated-by-caller"
    second = cache.snapshot(
        store, principal, as_of_tick=4, domains=("summary",))

    assert calls == 1
    assert second["summary"]["status"] == "paused"
    stats = cache.stats()
    assert {
        key: stats[key]
        for key in (
            "entries",
            "max_entries",
            "hits",
            "misses",
            "builds",
            "discarded_builds",
            "hit_ratio",
        )
    } == {
        "entries": 1,
        "max_entries": 4,
        "hits": 1,
        "misses": 1,
        "builds": 1,
        "discarded_builds": 0,
        "hit_ratio": 0.5,
    }
    assert stats["last_build_ms"] >= 0
    assert stats["build_ms_total"] >= stats["last_build_ms"]

    # A same-tick write changes sqlite total_changes even when no new
    # projection cursor is emitted, so a paused God-mode mutation cannot reuse
    # the preceding observer body.
    store.set_meta(status="running")
    third = cache.snapshot(
        store, principal, as_of_tick=4, domains=("summary",))
    assert calls == 2
    assert third["summary"]["status"] == "running"

    cache.clear()
    assert cache.stats()["entries"] == 0


def test_cache_does_not_publish_a_snapshot_built_across_a_write(store):
    _finalize_projection(store, 5)
    calls = 0

    def mutating_builder(current_store, _principal, **_kwargs):
        nonlocal calls
        calls += 1
        current_store.set_meta(phase=f"BUILD_{calls}")
        return {"summary": {"build": calls}}

    cache = ProjectionSnapshotCache(builder=mutating_builder)
    principal = Principal("ordinary-dashboard")

    assert cache.snapshot(
        store, principal, as_of_tick=5, domains=("summary",))[
            "summary"]["build"] == 1
    assert cache.snapshot(
        store, principal, as_of_tick=5, domains=("summary",))[
            "summary"]["build"] == 2
    assert cache.stats()["entries"] == 0
    assert cache.stats()["discarded_builds"] == 2


def test_tick_delta_and_http_snapshot_share_one_cached_build(
    economy,
    tmp_path,
):
    _finalize_projection(economy.store, 6)
    calls = 0

    def counting_builder(*args, **kwargs):
        nonlocal calls
        calls += 1
        return build_snapshot(*args, **kwargs)

    cache = ProjectionSnapshotCache(builder=counting_builder)
    world = SimpleNamespace(
        store=economy.store,
        economy=economy,
        config={
            "engine_semantics_version": 8,
            "operator_workspace": {
                "path": str(tmp_path / "operator-cache-test.db"),
                "csrf_token": "cache-test",
            },
        },
    )
    controller = SimpleNamespace(
        projection_cache=cache,
        hosted_safe=False,
    )
    app = FastAPI()
    install_v2_routes(app, world, controller)

    try:
        delta = projection_delta_message(
            economy.store,
            tick=6,
            projection_cache=cache,
        )
        with TestClient(app) as client:
            response = client.get("/api/v2/snapshot?tick=6")
        assert response.status_code == 200
        assert response.json()["data"] == delta["payload"]
        assert calls == 1
        assert cache.stats()["hits"] == 1
    finally:
        app.state.operator_workspace.close()
