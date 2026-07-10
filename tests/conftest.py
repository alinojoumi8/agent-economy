import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.store import Store
from engine.core import Economy


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "test.db"))
    s.init_run_meta("test", 7, {})
    yield s
    s.close()


@pytest.fixture
def economy(store):
    e = Economy(store, {"central_bank": {"max_step_bps": 50, "min_rate_bps": 0, "max_rate_bps": 2000}},
                random.Random(1), random.Random(2))
    e.ensure_system_accounts()
    return e


def make_bank(e, name="TestBank", reserves=10_000_00):
    res = e.ledger.create_account("bank", None, "reserve", label=f"{name}_res", opening_cents=reserves)
    eq = e.ledger.create_account("bank", None, "equity", label=f"{name}_eq")
    bid = e.store.insert("banks", name=name, reserve_account_id=res, equity_account_id=eq,
                         risk_policy_json="{}", reserve_requirement_bps=1000, status="open")
    e.store.execute("UPDATE accounts SET owner_id=? WHERE id=?", (bid, res))
    e.store.execute("UPDATE accounts SET owner_id=? WHERE id=?", (bid, eq))
    return bid


def make_agent(e, bank_id, name="Agent", cash=1_000_00, **kw):
    agent_id = e.store.insert("agents", name=name, kind=kw.pop("kind", "citizen"),
                              occupation=kw.pop("occupation", "worker"),
                              age=kw.pop("age", 35), alive=1, **kw)
    acct = e.ledger.create_account("agent", agent_id, "checking", bank_id=bank_id,
                                   label=f"{name}:chk", opening_cents=cash)
    e.store.update("agents", agent_id, checking_account_id=acct)
    return agent_id, acct
