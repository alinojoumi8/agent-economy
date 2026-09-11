"""Semantics-13 firm-funded construction; fixed quotes, escrow and valid-time views.

A permitted local firm may claim one vacant regional commercial parcel. Claims
last until cancellation, demolition or closure. Cancellation refunds all escrow;
completed buildings have no salvage refund. Completion runs after civic finalize.
"""
from __future__ import annotations

import json

CATALOG = [{"template_key": "workplace", "name": "Firm workplace", "cost_cents": 50000,
            "capacity": 12, "duration_ticks": 3, "zone_key": "commercial",
            "cancellation_refund_bps": 10000, "demolition_refund_cents": 0}]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class UrbanDevelopment:
    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.ledger = economy.ledger
        self.enabled = (economy.engine_semantics_version >= 13 and economy.city.enabled
                        and bool(economy.config.get("urban_development", {}).get("enabled", False)))

    def initialize(self, tick):
        if not self.enabled or self.store.scalar("SELECT COUNT(*) FROM urban_parcels"):
            return
        for region in self.store.query("SELECT id,x,y FROM regions ORDER BY id"):
            for slot in range(8):
                self.store.execute(
                    "INSERT OR IGNORE INTO urban_parcels(parcel_key,region_id,x,y,zone_key,blocked,created_tick) VALUES(?,?,?,?,?,?,?)",
                    (f"region:{region['id']}:parcel:{slot}", region['id'],
                     min(.98,max(.02,float(region['x'] or .5)+(slot%4-1.5)*.018)),
                     min(.98,max(.02,float(region['y'] or .5)+(.04 if slot<4 else .065))),
                     'commercial' if slot<7 else 'residential', 1 if slot==6 else 0, tick))
        self.snapshot(tick)

    def command(self, tick, actor_id, kind, action):
        if not self.enabled:
            return {"ok": False, "reason": "construction is unavailable"}
        payload = canonical({"type": kind, **{k:v for k,v in action.items() if k in {"firm_id", "parcel_id", "template_key", "project_id", "request_key"}}})
        receipt = self.store.query_one("SELECT * FROM construction_receipts WHERE actor_agent_id=? AND request_key=?", (actor_id,action['request_key']))
        if receipt:
            if receipt['payload_json'] != payload:
                return {"ok": False, "reason": "request key already used with different payload"}
            return {**json.loads(receipt['result_json']), 'idempotent_retry': True}
        actor = self.store.query_one("SELECT * FROM agents WHERE id=?",(actor_id,))
        if not actor or not actor['alive']:
            return {"ok": False, "reason": "living founder required"}
        project = None
        if kind != 'construct_building':
            project = self.store.query_one("SELECT * FROM construction_projects WHERE id=?",(action['project_id'],))
            if not project:
                return {"ok": False, "reason": "project not found"}
        firm_id = action['firm_id'] if project is None else project['firm_id']
        firm = self.store.query_one("SELECT * FROM firms WHERE id=?",(firm_id,))
        if not firm or firm['founder_agent_id'] != actor_id or firm['status'] not in ('private', 'listed'):
            return {"ok": False, "reason": "active firm's founder authority required"}
        if kind == 'construct_building':
            parcel = self.store.query_one("SELECT * FROM urban_parcels WHERE id=?",(action['parcel_id'],))
            if not parcel or parcel['region_id'] != firm['region_id']:
                return {"ok":False,"reason":"parcel must be in firm's region"}
            if parcel['blocked'] or parcel['zone_key'] != 'commercial' or parcel['owner_firm_id'] is not None:
                return {"ok":False,"reason":"parcel blocked, occupied or wrong zone"}
            if self.store.scalar("SELECT COUNT(*) FROM construction_projects WHERE firm_id=? AND status IN ('building','completed')",(firm_id,)):
                return {"ok":False,"reason":"firm already has an active construction claim"}
            if not self.store.scalar("SELECT COUNT(*) FROM civic_authorizations WHERE consumed_by_firm_id=? AND status='consumed'",(firm_id,)):
                return {"ok":False,"reason":"consumed business permit required"}
            quote = CATALOG[0]
            if action['template_key'] != quote['template_key']:
                return {"ok":False,"reason":"unknown template"}
            if self.ledger.balance(firm['account_id']) < quote['cost_cents']:
                return {"ok":False,"reason":"insufficient firm funds"}
            currency = self.store.scalar("SELECT currency_code FROM accounts WHERE id=?",(firm['account_id'],))
            pid = self.store.insert('construction_projects',actor_agent_id=actor_id,firm_id=firm_id,parcel_id=parcel['id'],template_key='workplace',status='building',requested_tick=tick,completion_tick=tick+quote['duration_ticks'],cost_cents=quote['cost_cents'],currency_code=currency,capacity=quote['capacity'])
            escrow = self.ledger.create_account('construction',pid,'escrow',label=f'construction:{pid}',currency_code=currency)
            txn = self.ledger.transfer(tick,firm['account_id'],escrow,quote['cost_cents'],kind='construction_escrow',memo=f'project {pid}')
            event = self.store.log_event(tick,'construction_started',{'project_id':pid,'firm_id':firm_id,'parcel_id':parcel['id'],'cost_cents':quote['cost_cents'],'completion_tick':tick+quote['duration_ticks']},subject_type='firm',subject_id=firm_id)
            self.store.update('construction_projects',pid,escrow_account_id=escrow,funding_transaction_id=txn,created_event_id=event)
            self.store.update('urban_parcels',parcel['id'],owner_firm_id=firm_id)
            result = {'ok':True,'project_id':pid,'status':'building','completion_tick':tick+quote['duration_ticks'],'event_id':event}
        else:
            required = 'building' if kind == 'cancel_construction' else 'completed'
            if project['status'] != required:
                return {'ok':False,'reason':f'project must be {required}'}
            status = 'cancelled' if required == 'building' else 'demolished'
            result = self.transition(tick, project, status)
        self.store.insert('construction_receipts',actor_agent_id=actor_id,request_key=action['request_key'],payload_json=payload,result_json=canonical(result))
        self.snapshot(tick)
        return result

    def transition(self, tick, project, status):
        pid = int(project['id'])
        updates = {'status':status}
        if project['status'] == 'building':
            account = self.store.scalar('SELECT account_id FROM firms WHERE id=?',(project['firm_id'],))
            updates['refund_transaction_id'] = self.ledger.transfer(tick,project['escrow_account_id'],account,project['cost_cents'],kind='construction_refund',memo=f'project {pid}')
        if project['place_id'] is not None:
            self.store.update('places',project['place_id'],active=0,closed_tick=tick)
            self.store.execute("UPDATE occupancy_leases SET status='cancelled',ended_tick=? WHERE place_id=? AND status='active'",(tick,project['place_id']))
        self.store.update('urban_parcels',project['parcel_id'],owner_firm_id=None)
        event = self.store.log_event(tick,'construction_'+status,{'project_id':pid,'firm_id':project['firm_id'],'parcel_id':project['parcel_id']},subject_type='firm',subject_id=project['firm_id'])
        updates['outcome_event_id'] = event
        self.store.update('construction_projects',pid,**updates)
        return {'ok':True,'project_id':pid,'status':status,'event_id':event}

    def close_firm(self, tick, firm_id):
        if not self.enabled:
            return
        for p in self.store.query("SELECT * FROM construction_projects WHERE firm_id=? AND status IN ('building','completed') ORDER BY id",(firm_id,)):
            self.transition(tick,p,'cancelled' if p['status']=='building' else 'closed')
        self.snapshot(tick)

    def founder_death(self,tick,agent_id):
        if not self.enabled:
            return
        for p in self.store.query("SELECT p.* FROM construction_projects p JOIN firms f ON f.id=p.firm_id WHERE f.founder_agent_id=? AND p.status='building' ORDER BY p.id",(agent_id,)):
            self.transition(tick,p,'cancelled')
        self.snapshot(tick)

    def finalize(self,tick):
        if not self.enabled:
            return
        for p in self.store.query("SELECT * FROM construction_projects WHERE status='building' ORDER BY completion_tick,id"):
            firm = self.store.query_one('SELECT * FROM firms WHERE id=?',(p['firm_id'],))
            alive = self.store.scalar('SELECT alive FROM agents WHERE id=?',(firm['founder_agent_id'],))
            if firm['status'] not in ('private', 'listed') or not alive:
                self.transition(tick,p,'cancelled')
                continue
            if p['completion_tick'] > tick:
                continue
            parcel = self.store.query_one('SELECT * FROM urban_parcels WHERE id=?',(p['parcel_id'],))
            if parcel['blocked']:
                self.transition(tick,p,'cancelled')
                continue
            sink = self.ledger.ensure_system_account('sys:construction',currency_code=p['currency_code'])
            txn = self.ledger.transfer(tick,p['escrow_account_id'],sink,p['cost_cents'],kind='construction_settlement',memo=f"project {p['id']}")
            # A new place preserves old coordinates and creation/closure truth.
            old = self.store.query("SELECT id FROM places WHERE owner_type='firm' AND owner_id=? AND kind='firm_workplace' AND active=1",(p['firm_id'],))
            for place in old:
                self.store.update('places',place['id'],active=0,closed_tick=tick)
                self.store.execute("UPDATE occupancy_leases SET status='cancelled',ended_tick=? WHERE place_id=? AND status='active'",(tick,place['id']))
            place_id = self.store.insert('places',place_key=f"construction:{p['id']}:workplace",region_id=parcel['region_id'],name=f"{firm['name']} Workplace",kind='firm_workplace',owner_type='firm',owner_id=p['firm_id'],x=parcel['x'],y=parcel['y'],capacity=p['capacity'],active=1,created_tick=tick,metadata_json=canonical({'construction_project_id':p['id']}))
            event = self.store.log_event(tick,'construction_completed',{'project_id':p['id'],'place_id':place_id,'firm_id':p['firm_id']},subject_type='firm',subject_id=p['firm_id'])
            self.store.update('construction_projects',p['id'],status='completed',place_id=place_id,settlement_transaction_id=txn,outcome_event_id=event)
        self.snapshot(tick)

    def snapshot(self,tick):
        # Public geometry/lifecycle only: never balances, escrow accounts, actor or request identity.
        parcels = [dict(r) for r in self.store.query('SELECT * FROM urban_parcels ORDER BY id')]
        projects = [dict(r) for r in self.store.query('SELECT id,firm_id,parcel_id,template_key,status,requested_tick,completion_tick,cost_cents,currency_code,capacity,place_id,created_event_id,outcome_event_id FROM construction_projects ORDER BY id')]
        projects = [{k:v for k,v in p.items() if v is not None or not k.endswith('_event_id')} for p in projects]
        data = canonical({'enabled':True,'catalog':CATALOG,'parcels':parcels,'projects':projects})
        prior = self.store.query_one('SELECT tick,data_json FROM urban_projection_history ORDER BY id DESC LIMIT 1')
        if prior and prior['tick'] == tick and prior['data_json'] == data:
            return
        self.store.insert('urban_projection_history',tick=tick,data_json=data)

    def projection(self,tick):
        if self.enabled:
            row = self.store.query_one('SELECT data_json FROM urban_projection_history WHERE tick<=? ORDER BY tick DESC,id DESC LIMIT 1',(tick,))
            if row:
                return json.loads(row['data_json'])
        return {'enabled':False,'catalog':[],'parcels':[],'projects':[]}
