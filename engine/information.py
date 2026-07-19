"""Structured claims, asymmetric exposure, distortion, and virality mechanics."""
from __future__ import annotations

import json
from typing import Any

from .store import Store


ITEM_TYPES = {"article", "earnings", "social_post", "repost", "correction"}
TRUTH_STATES = {"verified", "unverified", "false", "corrected"}


class InformationEconomy:
    def __init__(self, store: Store, config: dict | None = None):
        self.store = store
        self.config = config or {}
        self.enabled = config is not None and bool(self.config.get("enabled", True))
        self.base_reach = float(self.config.get("base_reach", 0.15))
        self.diffusion_window_ticks = max(
            1, int(self.config.get("diffusion_window_ticks", 30)))

    def create_claim(self, tick: int, actor_id: int | None, data: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": "information economy disabled"}
        sources = data.get("source_event_ids", [])
        if not isinstance(sources, list) or any(int(item) <= 0 for item in sources):
            return {"ok": False, "reason": "source_event_ids must contain positive ids"}
        existing = {int(row["id"]) for row in self.store.query(
            f"SELECT id FROM events WHERE id IN ({','.join('?' for _ in sources)})", sources)} if sources else set()
        if existing != {int(item) for item in sources}:
            return {"ok": False, "reason": "claim references missing source events"}
        truth = str(data.get("truth_status", "verified" if sources else "unverified"))
        if truth not in TRUTH_STATES:
            return {"ok": False, "reason": "invalid truth status"}
        if truth == "verified" and not sources:
            return {"ok": False, "reason": "verified claims require source events"}
        key = str(data.get("claim_key", "")).strip()[:160]
        predicate = str(data.get("predicate", "")).strip()[:100]
        if not key or not predicate:
            return {"ok": False, "reason": "claim_key and predicate are required"}
        claim_id = self.store.insert(
            "claims", tick=tick, claim_key=key,
            subject_type=str(data.get("subject_type", "event"))[:60],
            subject_id=(int(data["subject_id"]) if data.get("subject_id") is not None else None),
            predicate=predicate, value_json=json.dumps(data.get("value"), sort_keys=True),
            truth_status=truth, source_event_ids_json=json.dumps([int(item) for item in sources]),
            creator_agent_id=actor_id,
            correction_of_claim_id=(int(data["correction_of_claim_id"])
                                    if data.get("correction_of_claim_id") is not None else None))
        self.store.log_event(tick, "claim_created", {"claim_id": claim_id, "claim_key": key,
            "truth_status": truth, "source_event_ids": sources}, phase="EXECUTION",
            subject_type="claim", subject_id=claim_id, importance=1.2)
        return {"ok": True, "claim_id": claim_id}

    def publish_item(self, tick: int, actor_id: int | None, data: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": "information economy disabled"}
        claim_id = int(data.get("claim_id", 0))
        claim = self.store.query_one("SELECT * FROM claims WHERE id=?", (claim_id,))
        item_type = str(data.get("item_type", "social_post"))
        if not claim or item_type not in ITEM_TYPES:
            return {"ok": False, "reason": "valid claim and item_type required"}
        slant = max(-1.0, min(1.0, float(data.get("slant", 0.0))))
        tone = max(-1.0, min(1.0, float(data.get("tone", 0.0))))
        distortion = max(0.0, min(1.0, float(data.get("distortion", 0.0))))
        novelty = max(0.0, min(1.0, float(data.get("novelty", 0.5))))
        controversy = abs(slant) * 0.25 + abs(tone) * 0.2
        virality = max(0.0, min(1.0, self.base_reach + novelty * 0.35
                                + controversy - distortion * 0.1))
        parent = data.get("parent_item_id")
        if item_type == "repost" and not self.store.query_one(
                "SELECT 1 FROM information_items WHERE id=?", (int(parent or 0),)):
            return {"ok": False, "reason": "repost requires a parent item"}
        item_id = self.store.insert(
            "information_items", tick=tick, item_type=item_type, author_agent_id=actor_id,
            outlet_id=data.get("outlet_id"), claim_id=claim_id,
            parent_item_id=int(parent) if parent is not None else None,
            news_article_id=data.get("news_article_id"), body=str(data.get("body", ""))[:3000],
            slant=slant, tone=tone, distortion=distortion, novelty=novelty, virality=virality,
            source_event_ids_json=claim["source_event_ids_json"], status="published")
        self.store.log_event(tick, "information_published", {"item_id": item_id,
            "claim_id": claim_id, "item_type": item_type, "virality": round(virality, 4),
            "distortion": distortion}, phase="EXECUTION", subject_type="information_item",
            subject_id=item_id, importance=1.5 + virality)
        return {"ok": True, "item_id": item_id, "virality": virality}

    def repost(self, tick: int, actor_id: int, parent_item_id: int,
               commentary: str = "") -> dict[str, Any]:
        parent = self.store.query_one("SELECT * FROM information_items WHERE id=?", (parent_item_id,))
        if not parent:
            return {"ok": False, "reason": "parent item missing"}
        drift = ((actor_id * 17 + parent_item_id * 31 + tick * 13) % 7) / 100.0
        return self.publish_item(tick, actor_id, {
            "item_type": "repost", "claim_id": int(parent["claim_id"]),
            "parent_item_id": parent_item_id,
            "body": commentary or parent["body"], "slant": float(parent["slant"]),
            "tone": float(parent["tone"]),
            "distortion": min(1.0, float(parent["distortion"]) + drift),
            "novelty": max(0.1, float(parent["novelty"]) * 0.75),
        })

    def correct_claim(self, tick: int, actor_id: int, original_claim_id: int,
                      correction: dict[str, Any]) -> dict[str, Any]:
        original = self.store.query_one("SELECT * FROM claims WHERE id=?", (original_claim_id,))
        if not original:
            return {"ok": False, "reason": "original claim missing"}
        claim = self.create_claim(tick, actor_id, {
            "claim_key": f"{original['claim_key']}:correction:{tick}",
            "subject_type": original["subject_type"], "subject_id": original["subject_id"],
            "predicate": correction.get("predicate", original["predicate"]),
            "value": correction.get("value"), "truth_status": "corrected",
            "source_event_ids": correction.get("source_event_ids", []),
            "correction_of_claim_id": original_claim_id,
        })
        if not claim.get("ok"):
            return claim
        self.store.update("claims", original_claim_id, truth_status="false")
        return self.publish_item(tick, actor_id, {"item_type": "correction",
            "claim_id": claim["claim_id"], "body": correction.get("body", "Correction issued."),
            "tone": 0.0, "distortion": 0.0, "novelty": 0.9})

    def register_news_article(self, tick: int, article_id: int, outlet_id: int,
                              headline: str, body: str, source_event_ids: list[int],
                              tone: float, *, author_agent_id: int | None = None,
                              slant: float = 0.0) -> dict[str, Any]:
        claim = self.create_claim(tick, author_agent_id, {
            "claim_key": f"news:{article_id}", "subject_type": "news_article",
            "subject_id": article_id, "predicate": "reports", "value": headline,
            "truth_status": "verified" if source_event_ids else "unverified",
            "source_event_ids": source_event_ids,
        })
        if not claim.get("ok"):
            return claim
        return self.publish_item(tick, author_agent_id, {
            "item_type": "article", "claim_id": claim["claim_id"], "outlet_id": outlet_id,
            "news_article_id": article_id, "body": f"{headline}\n{body}",
            "tone": tone, "slant": slant, "distortion": 0.0, "novelty": 0.65,
        })

    def run_nightly(self, tick: int) -> None:
        if not self.enabled:
            return
        items = self.store.query(
            "SELECT i.*, c.value_json, c.truth_status FROM information_items i "
            "JOIN claims c ON c.id=i.claim_id WHERE i.status='published' "
            "AND i.tick<? AND i.tick>=? ORDER BY i.id",
            (tick, max(0, tick - self.diffusion_window_ticks)))
        agents = [
            (int(row["id"]), set(json.loads(row["media_diet_json"] or "[]")))
            for row in self.store.query(
                "SELECT id,media_diet_json FROM agents WHERE alive=1 ORDER BY id")
        ]
        for item in items:
            item_id = int(item["id"])
            exposed = {int(row["agent_id"]) for row in self.store.query(
                "SELECT agent_id FROM information_exposures WHERE item_id=?", (item_id,))}
            reach = int(max(0.0, min(1.0, float(item["virality"]))) * 1000)
            outlet_id = int(item["outlet_id"]) if item["outlet_id"] is not None else None
            perceived = {"claim_id": int(item["claim_id"]),
                         "value": json.loads(item["value_json"] or "null"),
                         "truth_status": item["truth_status"],
                         "confidence": round(max(0.0, 1.0 - float(item["distortion"])), 4)}
            perceived_json = json.dumps(perceived, sort_keys=True)
            channel = "social" if item["item_type"] in {"social_post", "repost"} else "news"
            for agent_id, diet in agents:
                if agent_id in exposed:
                    continue
                if item["outlet_id"] is not None:
                    if diet and outlet_id not in diet:
                        continue
                draw = (item_id * 1103515245 + agent_id * 2654435761 + tick * 97) % 1000
                if draw >= reach:
                    continue
                exposure_id = self.store.insert(
                    "information_exposures", item_id=item_id, agent_id=agent_id,
                    tick=tick, channel=channel,
                    version=1, perceived_claim_json=perceived_json,
                    distortion=float(item["distortion"]))
                self._update_beliefs(tick, agent_id, item, perceived, exposure_id)

    def expose_item(self, tick: int, agent_id: int, item_id: int,
                    *, channel: str = "commons") -> dict[str, Any]:
        """Record one explicit exposure and apply its factual belief update once."""
        if not self.enabled:
            return {"ok": False, "reason": "information economy disabled"}
        prior = self.store.query_one(
            "SELECT id FROM information_exposures WHERE item_id=? AND agent_id=?",
            (int(item_id), int(agent_id)))
        if prior is not None:
            return {"ok": True, "exposure_id": int(prior["id"]), "idempotent": True}
        item = self.store.query_one(
            "SELECT i.*,c.value_json,c.truth_status FROM information_items i "
            "JOIN claims c ON c.id=i.claim_id WHERE i.id=? AND i.status='published'",
            (int(item_id),))
        if item is None:
            return {"ok": False, "reason": "information item missing"}
        perceived = {
            "claim_id": int(item["claim_id"]),
            "value": json.loads(item["value_json"] or "null"),
            "truth_status": item["truth_status"],
            "confidence": round(max(0.0, 1.0 - float(item["distortion"])), 4),
        }
        exposure_id = self.store.insert(
            "information_exposures", item_id=int(item_id), agent_id=int(agent_id),
            tick=int(tick), channel=str(channel)[:40], version=1,
            perceived_claim_json=json.dumps(perceived, sort_keys=True),
            distortion=float(item["distortion"]))
        self._update_beliefs(tick, agent_id, item, perceived, exposure_id)
        return {"ok": True, "exposure_id": exposure_id, "idempotent": False}

    def _update_beliefs(self, tick: int, agent_id: int, item, perceived: dict[str, Any],
                        exposure_id: int) -> None:
        truth_weight = {"verified": 1.0, "corrected": 1.0, "unverified": 0.55, "false": 0.15}[
            perceived["truth_status"]]
        confidence = max(0.0, min(1.0, float(perceived["confidence"]) * truth_weight))
        key = f"claim:{int(item['claim_id'])}"
        self.store.execute(
            "INSERT INTO beliefs (agent_id,key,value,updated_tick) VALUES (?,?,?,?) "
            "ON CONFLICT(agent_id,key) DO UPDATE SET value=excluded.value, updated_tick=excluded.updated_tick",
            (agent_id, key, confidence, tick))
        previous = float(self.store.scalar(
            "SELECT value FROM beliefs WHERE agent_id=? AND key='sentiment'", (agent_id,), default=0.0))
        sentiment = max(-1.0, min(1.0, previous * 0.85 + float(item["tone"]) * confidence * 0.15))
        self.store.execute(
            "INSERT INTO beliefs (agent_id,key,value,updated_tick) VALUES (?,'sentiment',?,?) "
            "ON CONFLICT(agent_id,key) DO UPDATE SET value=excluded.value, updated_tick=excluded.updated_tick",
            (agent_id, sentiment, tick))
        self.store.log_event(tick, "information_exposed", {"exposure_id": exposure_id,
            "item_id": int(item["id"]), "claim_id": int(item["claim_id"]),
            "agent_id": agent_id, "confidence": confidence,
            "sentiment_before": previous, "sentiment_after": sentiment}, phase="NIGHT_CLOSE",
            subject_type="agent", subject_id=agent_id, importance=0.4)

    def exposure_feed(self, agent_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
        return [{**dict(row), "perceived_claim": json.loads(row["perceived_claim_json"] or "{}")}
                for row in self.store.query(
                    "SELECT e.*, i.item_type, i.body, i.tone, i.virality FROM information_exposures e "
                    "JOIN information_items i ON i.id=e.item_id WHERE e.agent_id=? "
                    "ORDER BY e.id DESC LIMIT ?", (agent_id, max(1, min(limit, 500))))]
