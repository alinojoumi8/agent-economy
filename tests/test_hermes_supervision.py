import json
import sqlite3
import sys
from pathlib import Path

import pytest

from scripts.hermes_supervision import supervise, save
from scripts.hermes_citizens import write_json


@pytest.mark.parametrize('writer', [save, write_json])
@pytest.mark.parametrize('failures', [2, 6])
def test_progress_replace_retries_transient_lock_without_losing_previous_file(tmp_path, monkeypatch, writer, failures):
    path = tmp_path / 'status.json'
    path.write_text('{"tick":1}')
    original = Path.replace
    attempts = []
    def replace(source, target):
        attempts.append(True)
        if len(attempts) <= failures:
            assert json.loads(path.read_text()) == {'tick': 1}
            raise PermissionError('temporary sharing violation')
        return original(source, target)
    monkeypatch.setattr(Path, 'replace', replace)
    if failures == 6:
        with pytest.raises(PermissionError): writer(path, {'tick': 2})
        assert json.loads(path.read_text()) == {'tick': 1}
        assert json.loads(path.with_suffix('.new').read_text()) == {'tick': 2}
    else:
        writer(path, {'tick': 2})
        assert json.loads(path.read_text()) == {'tick': 2}
    assert len(attempts) == min(6, failures + 1)


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
