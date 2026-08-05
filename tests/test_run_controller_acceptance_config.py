from types import SimpleNamespace

from server.controller import RunController


def _world(acceptance: dict) -> SimpleNamespace:
    return SimpleNamespace(
        config={"acceptance": acceptance},
        store=SimpleNamespace(tick=0),
        runtime=SimpleNamespace(participant=SimpleNamespace()),
        on_tick=None,
    )


def test_desktop_rehearsal_targets_do_not_lock_run_controls() -> None:
    controller = RunController(_world({
        "target_agents": 100,
        "rehearsal_ticks": 10,
        "min_peak_concurrency": 10,
    }))

    assert not controller.acceptance_configured


def test_acceptance_horizon_keeps_run_controls_governed() -> None:
    controller = RunController(_world({"min_ticks": 30, "min_agents": 95}))

    assert controller.acceptance_configured
    assert controller.acceptance_target_tick == 30
