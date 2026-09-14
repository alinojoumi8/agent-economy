"""Self-contained, read-only replay artifact exporter."""
from __future__ import annotations

import html
import json
from pathlib import Path

from engine.store import Store, load_json
from world.event_visibility import PUBLIC_REPORTABLE_EVENT_KINDS, public_event_payload

_PUBLIC_KINDS = tuple(sorted(PUBLIC_REPORTABLE_EVENT_KINDS))
_PUBLIC_KIND_MARKS = ",".join("?" for _ in _PUBLIC_KINDS)
# Resume/replay machinery, not run evidence: PRNG snapshots, the partial-tick
# decision buffer, and governor spend accounting stay inside the run database.
_INTERNAL_META_KEYS = (
    "prng_state", "lifecycle_prng_state", "phase_state_json", "governor_json")


def export_static_replay(store: Store, output_path: str | Path) -> Path:
    meta = dict(store.get_meta())
    config = load_json(meta.pop("config_json", None), {})
    for key in _INTERNAL_META_KEYS:
        meta.pop(key, None)
    data = {
        "meta": {**meta, "config": config},
        "regions": [dict(row) for row in store.query("SELECT * FROM regions ORDER BY id")],
        "agents": [dict(row) for row in store.query(
            "SELECT id,name,role,occupation,region_id,population_tier FROM agents WHERE alive=1 ORDER BY id")],
        "firms": [dict(row) for row in store.query("SELECT * FROM firms ORDER BY id")],
        "contracts": [dict(row) for row in store.query("SELECT * FROM contracts ORDER BY id")],
        "matters": [dict(row) for row in store.query("SELECT * FROM legal_matters ORDER BY id")],
        "bills": [dict(row) for row in store.query("SELECT * FROM bills ORDER BY id")],
        "information": [dict(row) for row in store.query("SELECT * FROM information_items ORDER BY id")],
        "metrics": [dict(row) for row in store.query("SELECT * FROM metrics ORDER BY tick,name")],
        # Only allowlisted public event kinds, each with its bounded public
        # payload projection. The raw event spine also holds private beliefs,
        # participant-control audit rows, and operator diagnostics.
        "events": [
            {
                "id": int(row["id"]), "tick": int(row["tick"]), "phase": row["phase"],
                "kind": str(row["kind"]), "subject_type": row["subject_type"],
                "subject_id": row["subject_id"], "importance": float(row["importance"]),
                "payload": public_event_payload(
                    str(row["kind"]), load_json(row["payload_json"], {}) or {}),
            }
            for row in store.query(
                f"SELECT * FROM events WHERE kind IN ({_PUBLIC_KIND_MARKS}) ORDER BY id",
                _PUBLIC_KINDS)
        ],
        "dataset_manifests": [dict(row) for row in store.query(
            "SELECT * FROM dataset_manifests ORDER BY dataset_key")],
        "calibration_targets": [dict(row) for row in store.query(
            "SELECT * FROM calibration_targets ORDER BY dataset_manifest_id,target_key")],
        "scenario_packs": [dict(row) for row in store.query("SELECT * FROM scenario_packs ORDER BY id")],
    }
    payload = json.dumps(data, sort_keys=True, default=str).replace("</", "<\\/")
    title = html.escape(f"Agent Economy replay {meta['run_id']}")
    document = f"""<!doctype html><html lang='en'><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>{title}</title>
<style>body{{font:15px system-ui;background:#07110f;color:#e7f1ed;margin:0;padding:2rem}}main{{max-width:1100px;margin:auto}}.card{{background:#10201c;border:1px solid #27483e;border-radius:14px;padding:1rem;margin:1rem 0}}input{{width:100%;padding:.7rem;background:#050a09;color:white;border:1px solid #385f52}}pre{{white-space:pre-wrap;max-height:55vh;overflow:auto}}</style>
<main><h1>{title}</h1><p>Self-contained deterministic replay. Structured state and provenance only; no private chain-of-thought.</p>
<div class='card' id='summary'></div><input id='filter' aria-label='Filter events' placeholder='Filter event kind…'><pre class='card' id='events'></pre></main>
<script id='replay-data' type='application/json'>{payload}</script><script>
const d=JSON.parse(document.querySelector('#replay-data').textContent);const s=document.querySelector('#summary');
s.textContent=`Tick ${{d.meta.tick}} · ${{d.agents.length}} agents · ${{d.firms.length}} firms · ${{d.contracts.length}} contracts · ${{d.bills.length}} bills`;
const out=document.querySelector('#events'),input=document.querySelector('#filter');function draw(){{const q=input.value.toLowerCase();out.textContent=d.events.filter(e=>!q||e.kind.toLowerCase().includes(q)).slice(-500).map(e=>`t${{e.tick}} ${{e.kind}} ${{JSON.stringify(e.payload)}}`).join('\n')}}input.oninput=draw;draw();</script></html>"""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8")
    return target
