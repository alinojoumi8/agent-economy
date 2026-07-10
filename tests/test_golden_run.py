"""Golden-run diff test (TECH-SPEC §14): the committed 10-tick event log must
reproduce exactly. A diff means engine behaviour changed — if the change is
intentional, regenerate with `python -m tests.golden_run` and commit the fixture."""
from tests.golden_run import GOLDEN_PATH, build_and_run, event_dump


def test_golden_run_event_log_matches_fixture(tmp_path):
    assert GOLDEN_PATH.exists(), \
        "golden fixture missing — generate it with `python -m tests.golden_run`"
    expected = GOLDEN_PATH.read_text(encoding="utf-8").splitlines()

    store, world = build_and_run(str(tmp_path / "golden.db"))
    ok, diag = world.economy.ledger.reconcile()
    assert ok, diag
    actual = event_dump(store)
    store.close()

    assert len(actual) == len(expected), \
        (f"event count changed: {len(actual)} vs golden {len(expected)} — "
         f"regenerate via `python -m tests.golden_run` if intentional")
    for i, (a, e) in enumerate(zip(actual, expected)):
        assert a == e, (f"golden divergence at event #{i}:\n  got:    {a}\n  golden: {e}\n"
                        f"regenerate via `python -m tests.golden_run` if intentional")
