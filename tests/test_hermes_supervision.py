import json
import sqlite3
import sys

import pytest

from scripts.hermes_supervision import supervise


@pytest.mark.parametrize('outcome', ['complete', 'abrupt_exit', 'early_clean_exit'])
def test_supervisor_records_actual_child_exit_and_saved_boundary(tmp_path, outcome):
    database = tmp_path / 'data/runs/one.db'
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE run_meta(tick INTEGER)')
        db.execute('INSERT INTO run_meta VALUES (63)')
    directory = tmp_path / 'data/control-plane/hermes-cohort/one'
    directory.mkdir(parents=True)
    (directory / 'status.json').write_text(json.dumps({'state': 'deciding', 'tick': 64}))
    code = 'import os; os._exit(23)' if outcome == 'abrupt_exit' else 'pass'
    if outcome == 'complete':
        code = ("import sqlite3,json; from pathlib import Path; "
                "db=sqlite3.connect('data/runs/one.db'); db.execute('UPDATE run_meta SET tick=141'); db.commit(); "
                "Path('data/control-plane/hermes-cohort/one/status.json').write_text(json.dumps({'state':'paused','tick':141}))")
    result = supervise(tmp_path, 'one', [sys.executable, '-c', code], 78, poll_seconds=0.01)
    status = json.loads((directory / 'status.json').read_text())
    events = [json.loads(line) for line in (directory / 'supervisor-events.jsonl').read_text().splitlines()]
    assert events[-1]['event'] == 'worker_exited'
    assert events[-1]['exit_code'] == (23 if outcome == 'abrupt_exit' else 0)
    assert events[-1]['target_tick'] == 141
    if outcome == 'complete':
        assert result == 0 and status == {'state': 'paused', 'tick': 141}
    else:
        assert result == 1 and status['state'] == 'error' and status['tick'] == 63
        assert events[-1]['expected'] is False
