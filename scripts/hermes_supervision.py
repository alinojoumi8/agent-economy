"""Observe the cohort worker without advancing the simulation or retrying actions."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time


def save(path, value):
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            # A transient Windows file lock must not kill an otherwise healthy
            # child. Persistent failures still reach the supervisor's journal.
            if attempt == 5:
                raise
            time.sleep(.02 * 2**attempt)


def saved_tick(root, run_id):
    with sqlite3.connect(f"file:{(root / 'data/runs' / (run_id + '.db')).as_posix()}?mode=ro", uri=True) as db:
        return int(db.execute('SELECT tick FROM run_meta').fetchone()[0])


def supervise(root, run_id, command, days, *, poll_seconds=5):
    directory = root / 'data/control-plane/hermes-cohort' / run_id
    directory.mkdir(parents=True, exist_ok=True)
    # Separate from the child's lock: a duplicate launcher must not overwrite
    # a working supervisor's process record or report a false worker failure.
    with (directory / 'supervisor.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        start_tick = saved_tick(root, run_id)
        started = time.time()
        record = {'pid': os.getpid(), 'run_id': run_id, 'started_at': started,
                  'starting_tick': start_tick, 'target_tick': start_tick + days}
        save(directory / 'operator-process.json', record)
        def event(kind, **fields):
            with (directory / 'supervisor-events.jsonl').open('a', encoding='utf-8') as log:
                log.write(json.dumps({'time': time.time(), 'event': kind, **record, **fields}) + '\n')
                log.flush()
        event('starting')
        child = None
        try:
            with (directory / 'operator.out.log').open('a', encoding='utf-8') as out, \
                 (directory / 'operator.err.log').open('a', encoding='utf-8') as err:
                child = subprocess.Popen(command, cwd=root, stdout=out, stderr=err)
                record['worker_pid'] = child.pid
                save(directory / 'operator-process.json', record)
                event('worker_started')
                while child.poll() is None:
                    save(directory / 'supervisor-health.json', {**record,
                        'checked_at': time.time(), 'saved_tick': saved_tick(root, run_id), 'state': 'running'})
                    time.sleep(poll_seconds)
                code = child.returncode
            tick = saved_tick(root, run_id)
            status_path = directory / 'status.json'
            status = json.loads(status_path.read_text()) if status_path.exists() else {}
            expected = code == 0 and status.get('state') == 'paused' and (
                tick == record['target_tick'] or (directory / 'STOP').exists())
            event('worker_exited', exit_code=code, saved_tick=tick, expected=expected)
            if not expected:
                save(status_path, {'state': 'error', 'tick': tick, 'exit_code': code,
                    'target_tick': record['target_tick'], 'worker_pid': child.pid,
                    'error': 'Hermes worker exited before its requested boundary. Saved decisions are retained; inspect supervisor-events.jsonl and operator.err.log.'})
            save(directory / 'supervisor-health.json', {**record, 'checked_at': time.time(),
                'saved_tick': tick, 'exit_code': code, 'state': 'paused' if expected else 'error'})
            return 0 if expected else 1
        except BaseException as exc:
            if child is not None and child.poll() is None:
                child.terminate()
                child.wait(timeout=15)
            # No provider response bodies, tokens, or private prompts in this journal.
            event('supervisor_exception', error_type=type(exc).__name__)
            save(directory / 'status.json', {'state': 'error', 'tick': saved_tick(root, run_id),
                'error': f'Supervisor interrupted: {type(exc).__name__}. Inspect the exit journal before resuming.'})
            raise
