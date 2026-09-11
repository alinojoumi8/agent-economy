"""Draft population journals remain authoritative in replay and research exports.

Only these disposable fixtures admit the unregistered population migration.
"""
import asyncio
import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil

import duckdb
import pytest

from engine.migrations.v026_population_residence import SQL
from engine.store import Store, open_read_only_connection
from research.export_bundle import ExportBundleError, ExportLimits, export_bundle, validate_bundle
from research.hashing import (
    HashContractError, canonical_hashes, load_hash_contract, verify_hash_contract,
)
from world.replay_verify import verify_replay_connections

from .test_bounded_export import _reseal
from .test_population_scenario import proposal, scenario_world


POPULATION_TABLES = {
    'person_residence_events', 'population_resident_census', 'population_movements',
    'population_movement_assents', 'population_commitment_endings',
    'population_scenario_manifest', 'population_scenario_receipts',
}


def stamp(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


@pytest.mark.parametrize('semantics,version', [(1, 1), (2, 1), (8, 1), (9, 2),
    (14, 2), (15, 3), (16, 3), (17, 4), (18, 5), (19, 6), (20, 7)])
def test_empty_population_extensions_preserve_each_older_contract(tmp_path, semantics, version):
    store = Store(str(tmp_path / 'legacy.db'), create=True)
    try:
        store.init_run_meta('legacy', 1, {'engine_semantics_version': semantics})
        before = canonical_hashes(store)
        assert before['contract_id'] == f'hash-contract-v{version}'
        store.conn.executescript(SQL)
        assert canonical_hashes(store) == before
    finally:
        store.close()


def test_all_population_journals_require_the_new_authoritative_contract(scenario_world):
    world = scenario_world([proposal()])
    contract = load_hash_contract('research/hash-contract-v8.json')
    assert set(contract['population_tables']) == POPULATION_TABLES
    assert POPULATION_TABLES <= set(contract['authoritative_tables'])
    assert not POPULATION_TABLES & set(contract['derived_tables'] + contract['excluded_tables'])
    assert not POPULATION_TABLES & set(contract['excluded_columns'])
    assert verify_hash_contract(world.store)['contract_id'] == 'hash-contract-v8'
    for version in range(1, 8):
        with pytest.raises(HashContractError, match='Semantics 21 requires hash-contract-v8'):
            canonical_hashes(world.store, load_hash_contract(f'research/hash-contract-v{version}.json'))
    # Fault injection: relabeling a populated world cannot omit its new journals.
    world.store.execute('UPDATE run_meta SET config_json=?',
                        (json.dumps({'engine_semantics_version': 20}),))
    with pytest.raises(HashContractError, match='populated population history'):
        canonical_hashes(world.store)


@pytest.mark.parametrize('change,message', [
    ('ALTER TABLE person_residence_events ADD COLUMN unclassified TEXT', 'unclassified storage column'),
    ('DROP TABLE population_scenario_receipts', 'tables are absent'),
])
def test_incomplete_population_storage_is_rejected(tmp_path, change, message):
    store = Store(str(tmp_path / 'draft.db'), create=True)
    try:
        store.conn.executescript(SQL)
        store.init_run_meta('draft', 1, {'engine_semantics_version': 21})
        store.execute(change)
        with pytest.raises(HashContractError, match=message):
            canonical_hashes(store)
    finally:
        store.close()


def test_resident_census_changes_authoritative_evidence(scenario_world):
    world = scenario_world([proposal()])
    before = canonical_hashes(world.store)
    # Simulate source corruption while preserving the census arithmetic checks.
    world.store.execute('DROP TRIGGER resident_census_immutable')
    world.store.execute('UPDATE population_resident_census SET opening_residents=opening_residents+1, '
                        'closing_residents=closing_residents+1,total_known_living=total_known_living+1 WHERE tick=0')
    after = canonical_hashes(world.store)
    assert before['authoritative_sha256'] != after['authoritative_sha256']
    assert before['derived_sha256'] == after['derived_sha256']


@pytest.mark.parametrize('alteration', [
    'derived', 'excluded', 'excluded_column', 'json_treatment', 'model_redaction', 'population_inventory',
])
def test_v8_label_cannot_hide_changed_hash_or_privacy_definitions(scenario_world, tmp_path, alteration):
    world = scenario_world([proposal()])
    before = canonical_hashes(world.store)
    contract = copy.deepcopy(load_hash_contract('research/hash-contract-v8.json'))
    if alteration in ('derived', 'excluded'):
        contract['authoritative_tables'].remove('person_residence_events')
        contract[f'{alteration}_tables'].append('person_residence_events')
    elif alteration == 'excluded_column':
        contract['excluded_columns']['person_residence_events'] = ['state']
    elif alteration == 'json_treatment':
        contract['json_suffixes'] = []
    elif alteration == 'model_redaction':
        contract['default_export_redactions']['llm_calls'] = []
    else:
        contract['population_tables'] = []
    path = tmp_path / 'changed-contract.json'
    path.write_text(json.dumps(contract), encoding='utf-8')
    with pytest.raises(HashContractError, match='definitions must match'):
        canonical_hashes(world.store, contract)
    with pytest.raises(HashContractError, match='definitions must match'):
        export_bundle(world.store, tmp_path / 'changed-export', contract_path=path)
    assert not list((tmp_path / 'changed-export').glob('*/manifest.json'))
    assert canonical_hashes(world.store) == before


@pytest.fixture
def closed_population_source(scenario_world):
    entries = [proposal(), {**proposal('back', tick=3, due=5, cause='return'),
                             'destination_region_id': 2}]
    world = scenario_world(entries, 'population-source')
    for day in range(1, 7):
        if day in (2, 4):
            result = asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
            assert result['active_tick'] == day
            scenario_world.close(world)
            world = scenario_world(entries, 'population-source')
        asyncio.run(world.step())
        assert world.store.tick == day
        assert world.economy.ledger.reconcile()[0]
    path = Path(world.store.path)
    scenario_world.close(world)
    before = stamp(path)
    yield path, entries
    assert stamp(path) == before
    assert not any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))


def test_closed_restarted_population_source_replays_and_exports_every_journal(
        closed_population_source, scenario_world, tmp_path):
    path, entries = closed_population_source
    replay = scenario_world(entries, 'population-replay', replay_source=path)
    for _ in range(6):
        asyncio.run(replay.step())
    replay_path = Path(replay.store.path)
    scenario_world.close(replay)
    replay_stamp = stamp(replay_path)
    with closing(open_read_only_connection(path, require_closed=True)) as source, \
         closing(open_read_only_connection(replay_path, require_closed=True)) as recorded:
        proof = verify_replay_connections(source, recorded)
        assert proof['exact'], proof['differences']
        original_hashes, replay_hashes = canonical_hashes(source), canonical_hashes(recorded)
        for table in POPULATION_TABLES:
            assert original_hashes['tables'][table] == replay_hashes['tables'][table]
            assert original_hashes['tables'][table]['row_count'] > 0
        stats = {}
        first = export_bundle(source, tmp_path / 'export-first', stats=stats,
                              limits=ExportLimits(max_batch_rows=7))
        second = export_bundle(source, tmp_path / 'export-second',
                               limits=ExportLimits(max_batch_rows=128))
        assert first.name == second.name
        manifest = validate_bundle(first, database=source)
        assert manifest == validate_bundle(second, database=source)
        assert manifest['contract_id'] == 'hash-contract-v8'
        assert manifest['schema_version'] == 26
        assert stats['peak_batch_rows'] <= 7
        assert stats['status'] == 'complete'
        replay_export = export_bundle(recorded, tmp_path / 'export-replay')
        validate_bundle(replay_export, database=recorded)
        with duckdb.connect() as reader:
            for table in sorted(POPULATION_TABLES):
                actual = reader.execute('SELECT * FROM read_parquet(?)', [str(first / f'{table}.parquet')]).fetchall()
                expected = [tuple(row) for row in source.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                assert sorted(actual) == sorted(expected)
            census = reader.execute('SELECT tick,closing_residents,known_living_outside,total_known_living,returns,arrivals '
                'FROM read_parquet(?) ORDER BY tick', [str(first / 'population_resident_census.parquet')]).fetchall()
            assert census == [(day, 46 if 2 <= day <= 4 else 47, 1 if 2 <= day <= 4 else 0,
                               47, 1 if day == 5 else 0, 0) for day in range(7)]
            assert reader.execute('SELECT COUNT(*) FROM read_parquet(?) WHERE request_json IS NOT NULL '
                'OR response_json IS NOT NULL', [str(first / 'llm_calls.parquet')]).fetchone()[0] == 0
        assert manifest['tables']['llm_calls']['redactions']['request_json'] > 0
        assert source.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
    assert stamp(replay_path) == replay_stamp


def test_resealed_population_export_cannot_change_the_source_census(closed_population_source, tmp_path):
    source_path, _ = closed_population_source
    with closing(open_read_only_connection(source_path, require_closed=True)) as source:
        original = export_bundle(source, tmp_path / 'original')
        corrupt = tmp_path / 'corrupt'
        shutil.copytree(original, corrupt)
        target = corrupt / 'population_resident_census.parquet'
        replacement = corrupt / 'changed.parquet'
        with duckdb.connect() as connection:
            connection.execute('CREATE TABLE original AS SELECT * FROM read_parquet(?)', [str(target)])
            escaped = str(replacement).replace("'", "''")
            connection.execute("COPY (SELECT * REPLACE (known_living_outside+1 AS known_living_outside, "
                "total_known_living+1 AS total_known_living) FROM original ORDER BY tick) "
                f"TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        replacement.replace(target)
        _reseal(corrupt)
        # A self-consistent archive alone cannot authenticate its source claims.
        validate_bundle(corrupt)
        with pytest.raises(ExportBundleError, match='source content mismatch: population_resident_census'):
            validate_bundle(corrupt, database=source)
        validate_bundle(original, database=source)
