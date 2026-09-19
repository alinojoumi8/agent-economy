import json
import sqlite3

import pytest

from research.hashing import canonical_hashes, verify_hash_contract, load_hash_contract, V2_CONTRACT_PATH, HashContractError
from research.export_bundle import export_bundle, validate_bundle
from run import open_run
from scripts.enable_frontier import enable, fingerprint
from tests.test_frontier import config


def test_upgrade_rehearses_then_preserves_existing_rows_and_refuses_repeat(tmp_path):
    cfg = config(); cfg.pop('frontier')
    folder = tmp_path/'data/runs'; folder.mkdir(parents=True)
    store, world, rid = open_run(cfg, None, None, data_dir=folder)
    before = {table: fingerprint(store.conn, table) for table in ('agents','events','memories','ledger_entries')}
    world.close()
    result = enable(rid, root=tmp_path)
    assert result['applied'] is False
    with sqlite3.connect(folder/f'{rid}.db') as db:
        assert 'frontier' not in json.loads(db.execute('SELECT config_json FROM run_meta').fetchone()[0])
    result = enable(rid, apply=True, root=tmp_path)
    assert result['activation_tick'] == 1
    store, world, _ = open_run({}, rid, None, data_dir=folder)
    try:
        assert all(fingerprint(store.conn, table) == digest for table,digest in before.items())
        assert not store.scalar('SELECT COUNT(*) FROM regions')
        assert world.config['frontier']['activation_tick'] == 1
    finally:
        world.close()
    with pytest.raises(ValueError, match='already'):
        enable(rid, apply=True, root=tmp_path)


def test_frontier_hash_contract_cannot_omit_history_and_exports_it(tmp_path):
    store, world, _ = open_run(config(), None, None, data_dir=tmp_path/'runs')
    try:
        assert verify_hash_contract(store)['contract_id'] == 'hash-contract-v10'
        before = canonical_hashes(store)
        world.economy.frontier.run_nightly(1)
        assert canonical_hashes(store) != before
        with pytest.raises(HashContractError, match='requires hash-contract-v10'):
            verify_hash_contract(store, load_hash_contract(V2_CONTRACT_PATH))
        # Even changing the config cannot hide populated frontier state.
        cfg = config(); cfg.pop('frontier'); store.set_meta(config_json=json.dumps(cfg))
        with pytest.raises(HashContractError, match='requires hash-contract-v10'):
            verify_hash_contract(store)
        store.set_meta(config_json=json.dumps(config()))
        store.commit()
        bundle = export_bundle(store, tmp_path/'bundle')
        manifest = validate_bundle(bundle, database=store)
        assert manifest['contract_id'] == 'hash-contract-v10'
    finally:
        world.close()
