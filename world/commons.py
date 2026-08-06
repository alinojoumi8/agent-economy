"""Deterministic public social layer for semantics 10.

Commons delivery is deliberately separate from information exposure: rendering a
feed writes an impression, while only ``read`` may create a factual exposure.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from agents.memory import Memory
from causal import CausalLinkService
from engine.core import Economy
from engine.store import load_json


@dataclass
class CommonsError(RuntimeError):
    status_code: int
    message: str

    def __str__(self) -> str:
        return self.message


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CommonsService:
    """Stateful Commons operations backed only by run-local deterministic state."""

    def __init__(self, economy: Economy, memory: Memory | None = None):
        self.economy = economy
        self.store = economy.store
        self.memory = memory
        self.causal = CausalLinkService(self.store)

    def ensure_profile(self, agent_id: int, *, biography: str = "") -> dict[str, Any]:
        agent = self._living_agent(agent_id)
        row = self.store.query_one("SELECT * FROM commons_profiles WHERE agent_id=?", (agent_id,))
        if row is None:
            self.store.execute(
                "INSERT INTO commons_profiles(agent_id,display_name,biography,reputation,status,"
                "created_tick,updated_tick) VALUES(?,?,?,0,'active',?,?)",
                (agent_id, str(agent["name"])[:80], str(biography).strip()[:500],
                 self.store.tick, self.store.tick),
            )
            row = self.store.query_one(
                "SELECT * FROM commons_profiles WHERE agent_id=?", (agent_id,))
        return self._profile_document(row)

    def profile(self, agent_id: int) -> dict[str, Any]:
        row = self.store.query_one(
            "SELECT p.*,a.occupation,a.alive,c.status AS connection_status "
            "FROM commons_profiles p JOIN agents a ON a.id=p.agent_id "
            "LEFT JOIN external_agent_connections c ON c.actor_id=p.agent_id "
            "WHERE p.agent_id=?", (int(agent_id),))
        if row is None:
            return self.ensure_profile(int(agent_id))
        return self._profile_document(row)

    def create_community(self, actor_id: int, *, name: str, description: str = "",
                         visibility: str = "public") -> dict[str, Any]:
        self._living_agent(actor_id)
        clean_name = str(name).strip()[:120]
        if not clean_name:
            raise CommonsError(400, "community name is required")
        if visibility not in {"public", "members"}:
            raise CommonsError(400, "invalid community visibility")
        base = re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-")[:70] or "community"
        slug = base
        suffix = 2
        while self.store.query_one("SELECT 1 FROM commons_communities WHERE slug=?", (slug,)):
            slug = f"{base[:70-len(str(suffix))]}-{suffix}"
            suffix += 1
        community_id = self.store.insert(
            "commons_communities", slug=slug, name=clean_name,
            description=str(description).strip()[:1000], visibility=visibility,
            owner_agent_id=actor_id, status="active", created_tick=self.store.tick)
        self.store.insert(
            "commons_memberships", community_id=community_id, agent_id=actor_id,
            role="owner", status="active", joined_tick=self.store.tick,
            updated_tick=self.store.tick)
        event_id = self.store.log_event(
            self.store.tick, "commons_community_created",
            {"community_id": community_id, "slug": slug, "owner_agent_id": actor_id},
            phase="COMMONS", subject_type="agent", subject_id=actor_id, importance=1.0)
        self.store.commit()
        return {"id": community_id, "slug": slug, "name": clean_name,
                "visibility": visibility, "created_event_id": event_id}

    def join_community(self, actor_id: int, community_id: int) -> dict[str, Any]:
        self._living_agent(actor_id)
        community = self._community(community_id)
        self.store.execute(
            "INSERT INTO commons_memberships(community_id,agent_id,role,status,joined_tick,updated_tick) "
            "VALUES(?,?,'member','active',?,?) ON CONFLICT(community_id,agent_id) DO UPDATE SET "
            "status='active',updated_tick=excluded.updated_tick",
            (community_id, actor_id, self.store.tick, self.store.tick))
        self.store.log_event(
            self.store.tick, "commons_membership_joined",
            {"community_id": community_id, "agent_id": actor_id}, phase="COMMONS",
            subject_type="agent", subject_id=actor_id, importance=0.5)
        self.store.commit()
        return {"ok": True, "community_id": int(community["id"]), "agent_id": actor_id}

    def follow(self, actor_id: int, target_agent_id: int, *, active: bool = True) -> dict[str, Any]:
        self._living_agent(actor_id)
        self._living_agent(target_agent_id)
        if actor_id == target_agent_id:
            raise CommonsError(400, "an agent cannot follow itself")
        status = "active" if active else "unfollowed"
        self.store.execute(
            "INSERT INTO commons_follows(follower_agent_id,followed_agent_id,created_tick,status) "
            "VALUES(?,?,?,?) ON CONFLICT(follower_agent_id,followed_agent_id) DO UPDATE SET "
            "status=excluded.status",
            (actor_id, target_agent_id, self.store.tick, status))
        self.store.log_event(
            self.store.tick, "commons_follow_changed",
            {"follower_agent_id": actor_id, "followed_agent_id": target_agent_id,
             "status": status}, phase="COMMONS", subject_type="agent",
            subject_id=actor_id, importance=0.3)
        self.store.commit()
        return {"ok": True, "status": status}

    def publish(self, actor_id: int, *, body: str, community_id: int | None = None,
                parent_entry_id: int | None = None, entry_type: str = "post",
                claim_id: int | None = None) -> dict[str, Any]:
        self._living_agent(actor_id)
        self.ensure_profile(actor_id)
        text = str(body).strip()[:3000]
        if not text:
            raise CommonsError(400, "post body is required")
        if entry_type not in {"post", "comment", "repost", "quote"}:
            raise CommonsError(400, "invalid entry type")
        root_id = None
        if parent_entry_id is not None:
            parent = self.store.query_one(
                "SELECT * FROM commons_entries WHERE id=? AND status='published'",
                (int(parent_entry_id),))
            if parent is None:
                raise CommonsError(404, "parent entry not found")
            root_id = int(parent["root_entry_id"] or parent["id"])
            community_id = int(parent["community_id"]) if parent["community_id"] is not None else community_id
            if entry_type == "post":
                entry_type = "comment"
        elif entry_type != "post":
            raise CommonsError(400, "non-post entries require a parent")
        if community_id is not None:
            community = self._community(int(community_id))
            if community["visibility"] == "members" and not self._is_member(actor_id, int(community_id)):
                raise CommonsError(403, "community membership is required")
        information_item_id = None
        if claim_id is not None:
            claim = self.store.query_one("SELECT id FROM claims WHERE id=?", (int(claim_id),))
            if claim is None:
                raise CommonsError(404, "claim not found")
            published = self.economy.information.publish_item(
                self.store.tick, actor_id,
                {"item_type": "repost" if entry_type == "repost" else "social_post",
                 "claim_id": int(claim_id), "body": text, "tone": 0.0,
                 "slant": 0.0, "distortion": 0.0, "novelty": 0.5,
                 **({"parent_item_id": int(parent["information_item_id"])}
                    if entry_type == "repost" and parent["information_item_id"] is not None else {})})
            if not published.get("ok"):
                raise CommonsError(409, str(published.get("reason", "claim cannot be published")))
            information_item_id = int(published["item_id"])
        event_id = self.store.log_event(
            self.store.tick, "commons_entry_published",
            {"author_agent_id": actor_id, "entry_type": entry_type,
             "community_id": community_id, "claim_id": claim_id}, phase="COMMONS",
            subject_type="agent", subject_id=actor_id, importance=0.8)
        entry_id = self.store.insert(
            "commons_entries", community_id=community_id, author_agent_id=actor_id,
            entry_type=entry_type, root_entry_id=root_id,
            parent_entry_id=int(parent_entry_id) if parent_entry_id is not None else None,
            body_text=text, claim_id=int(claim_id) if claim_id is not None else None,
            information_item_id=information_item_id, created_tick=self.store.tick,
            status="published", created_event_id=event_id)
        self.store.commit()
        return self.entry(entry_id)

    def react(self, actor_id: int, entry_id: int, reaction: str,
              *, active: bool = True) -> dict[str, Any]:
        self._living_agent(actor_id)
        entry = self._entry(entry_id)
        if reaction not in {"like", "agree", "disagree", "insightful"}:
            raise CommonsError(400, "invalid reaction")
        status = "active" if active else "removed"
        self.store.execute(
            "INSERT INTO commons_reactions(entry_id,agent_id,reaction,created_tick,status) "
            "VALUES(?,?,?,?,?) ON CONFLICT(entry_id,agent_id,reaction) DO UPDATE SET "
            "status=excluded.status",
            (entry_id, actor_id, reaction, self.store.tick, status))
        points = {"like": 1, "agree": 1, "disagree": 0, "insightful": 2}[reaction]
        if not active:
            points = -points
        self.ensure_profile(int(entry["author_agent_id"]))
        self.store.execute(
            "UPDATE commons_profiles SET reputation=reputation+?,updated_tick=? WHERE agent_id=?",
            (points, self.store.tick, int(entry["author_agent_id"])))
        self.store.log_event(
            self.store.tick, "commons_reaction_changed",
            {"entry_id": entry_id, "agent_id": actor_id, "reaction": reaction,
             "status": status}, phase="COMMONS", subject_type="agent",
            subject_id=actor_id, importance=0.2)
        self.store.commit()
        return {"ok": True, "status": status}

    def feed(self, viewer_agent_id: int, *, kind: str = "chronological",
             community_id: int | None = None, limit: int = 30) -> dict[str, Any]:
        self._living_agent(viewer_agent_id)
        self.ensure_profile(viewer_agent_id)
        kind = str(kind)
        if kind not in {"chronological", "hot", "community", "profile"}:
            raise CommonsError(400, "invalid feed kind")
        algorithm = "hot" if kind == "hot" else "chronological"
        policy = self.store.query_one(
            "SELECT * FROM commons_feed_policies WHERE algorithm=? AND active=1 "
            "ORDER BY version DESC,id DESC LIMIT 1", (algorithm,))
        if policy is None:
            raise CommonsError(503, "feed policy unavailable")
        params: list[Any] = []
        clauses = ["e.status='published'", "a.alive=1"]
        if community_id is not None:
            community = self._community(int(community_id))
            if community["visibility"] == "members" and not self._is_member(
                    viewer_agent_id, int(community_id)):
                raise CommonsError(403, "community membership is required")
            clauses.append("e.community_id=?")
            params.append(int(community_id))
        else:
            clauses.append(
                "(e.community_id IS NULL OR c.visibility='public' OR EXISTS("
                "SELECT 1 FROM commons_memberships cm WHERE cm.community_id=e.community_id "
                "AND cm.agent_id=? AND cm.status='active'))")
            params.append(viewer_agent_id)
        rows = self.store.query(
            "SELECT e.*,a.name AS author_name,c.slug AS community_slug,c.name AS community_name,"
            "(SELECT COUNT(*) FROM commons_reactions r WHERE r.entry_id=e.id AND r.status='active') "
            "AS reaction_count,(SELECT COUNT(*) FROM commons_entries q WHERE q.parent_entry_id=e.id "
            "AND q.status='published') AS reply_count FROM commons_entries e "
            "JOIN agents a ON a.id=e.author_agent_id "
            "LEFT JOIN commons_communities c ON c.id=e.community_id WHERE "
            + " AND ".join(clauses) + " ORDER BY e.id",
            tuple(params))
        scored: list[tuple[tuple[int, int], Any, dict[str, int]]] = []
        for row in rows:
            age = max(0, self.store.tick - int(row["created_tick"]))
            components = {"reactions": int(row["reaction_count"]),
                          "replies": int(row["reply_count"]), "age_ticks": age}
            hot_score = components["reactions"] * 1000 + components["replies"] * 500 - age
            key = (hot_score, int(row["id"])) if algorithm == "hot" else (
                int(row["created_tick"]), int(row["id"]))
            scored.append((key, row, components))
        scored.sort(key=lambda item: item[0], reverse=True)
        candidates = [int(item[1]["id"]) for item in scored]
        candidate_hash = _canonical_hash({"policy_id": int(policy["id"]),
                                          "candidate_ids": sorted(candidates)})
        delivered = []
        for position, (_key, row, components) in enumerate(scored[:max(1, min(limit, 100))], 1):
            dedupe = _canonical_hash({"viewer": viewer_agent_id, "entry": int(row["id"]),
                                      "tick": self.store.tick, "kind": kind,
                                      "policy": int(policy["id"])})
            self.store.execute(
                "INSERT OR IGNORE INTO commons_feed_impressions(dedupe_key,viewer_agent_id,entry_id,"
                "delivered_tick,feed_kind,candidate_set_hash,score_components_json,position,policy_id) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (dedupe, viewer_agent_id, int(row["id"]), self.store.tick, kind,
                 candidate_hash, json.dumps(components, sort_keys=True), position,
                 int(policy["id"])))
            impression = self.store.query_one(
                "SELECT id,read_tick,exposure_id FROM commons_feed_impressions WHERE dedupe_key=?",
                (dedupe,))
            self.causal.create(
                "commons_entry", int(row["id"]),
                "feed_impression", int(impression["id"]),
                "delivered", "engine", created_tick=self.store.tick,
                provenance={"feed_kind": kind, "position": position,
                            "policy_id": int(policy["id"]),
                            "candidate_set_hash": candidate_hash})
            delivered.append({**self._entry_document(row), "impression_id": int(impression["id"]),
                              "position": position, "score_components": components,
                              "read": impression["read_tick"] is not None})
        self.store.commit()
        return {"feed_kind": kind, "policy": {"id": int(policy["id"]),
                "key": str(policy["policy_key"]), "version": int(policy["version"]),
                "algorithm": str(policy["algorithm"])},
                "candidate_set_hash": candidate_hash, "entries": delivered}

    def read(self, viewer_agent_id: int, impression_id: int) -> dict[str, Any]:
        self._living_agent(viewer_agent_id)
        row = self.store.query_one(
            "SELECT i.*,e.author_agent_id,e.body_text,e.claim_id,e.information_item_id "
            "FROM commons_feed_impressions i JOIN commons_entries e ON e.id=i.entry_id "
            "WHERE i.id=? AND i.viewer_agent_id=?",
            (int(impression_id), viewer_agent_id))
        if row is None:
            raise CommonsError(404, "feed impression not found")
        if row["read_tick"] is not None:
            return {"ok": True, "impression_id": int(impression_id),
                    "read_tick": int(row["read_tick"]),
                    "exposure_id": row["exposure_id"], "idempotent": True}
        exposure_id = None
        memory_id = None
        if row["information_item_id"] is not None:
            exposure = self.economy.information.expose_item(
                self.store.tick, viewer_agent_id, int(row["information_item_id"]),
                channel="commons")
            if exposure.get("ok"):
                exposure_id = int(exposure["exposure_id"])
                self.causal.create(
                    "feed_impression", int(impression_id),
                    "information_exposure", exposure_id,
                    "observed", "engine", created_tick=self.store.tick,
                    provenance={"channel": "commons", "explicit_read": True})
                belief = self.store.query_one(
                    "SELECT id FROM beliefs WHERE agent_id=? AND key=?",
                    (viewer_agent_id, f"claim:{int(row['claim_id'])}"))
                if belief is not None:
                    self.causal.create(
                        "information_exposure", exposure_id,
                        "belief", int(belief["id"]),
                        "triggered", "engine", created_tick=self.store.tick,
                        provenance={"claim_id": int(row["claim_id"])})
        else:
            if self.memory is not None:
                memory_id = self.memory.observe(
                    viewer_agent_id, self.store.tick,
                    f"Commons post by agent {int(row['author_agent_id'])}: "
                    f"{str(row['body_text'])[:500]}", importance=1.0,
                    entities=["commons", f"agent:{int(row['author_agent_id'])}"])
                self.causal.create(
                    "feed_impression", int(impression_id),
                    "memory", memory_id, "observed", "engine",
                    created_tick=self.store.tick,
                    provenance={"channel": "commons", "explicit_read": True,
                                "claimless": True})
            self._strengthen_social_tie(viewer_agent_id, int(row["author_agent_id"]))
        self.store.execute(
            "UPDATE commons_feed_impressions SET read_tick=?,exposure_id=? WHERE id=? AND read_tick IS NULL",
            (self.store.tick, exposure_id, int(impression_id)))
        event_id = self.store.log_event(
            self.store.tick, "commons_entry_read",
            {"impression_id": int(impression_id), "entry_id": int(row["entry_id"]),
             "viewer_agent_id": viewer_agent_id, "exposure_id": exposure_id},
            phase="COMMONS", subject_type="agent", subject_id=viewer_agent_id,
            importance=0.4)
        self.store.commit()
        return {"ok": True, "impression_id": int(impression_id),
                "read_tick": self.store.tick, "exposure_id": exposure_id,
                "event_id": event_id, "memory_id": memory_id,
                "idempotent": False}

    def moderate(self, moderator_agent_id: int, entry_id: int, *, action: str,
                 reason: str) -> dict[str, Any]:
        self._living_agent(moderator_agent_id)
        entry = self._entry(entry_id)
        if action not in {"label", "hide", "remove", "restore", "limit_author"}:
            raise CommonsError(400, "invalid moderation action")
        if entry["community_id"] is None or not self._is_moderator(
                moderator_agent_id, int(entry["community_id"])):
            raise CommonsError(403, "an in-world moderator role is required")
        clean_reason = str(reason).strip()[:500]
        if not clean_reason:
            raise CommonsError(400, "moderation reason is required")
        status_by_action = {"hide": "hidden", "remove": "removed", "restore": "published"}
        if action in status_by_action:
            self.store.execute("UPDATE commons_entries SET status=? WHERE id=?",
                               (status_by_action[action], entry_id))
        if action == "label":
            self.store.execute("UPDATE commons_entries SET moderation_label=? WHERE id=?",
                               (clean_reason, entry_id))
        if action == "limit_author":
            self.ensure_profile(int(entry["author_agent_id"]))
            self.store.execute("UPDATE commons_profiles SET status='limited',updated_tick=? WHERE agent_id=?",
                               (self.store.tick, int(entry["author_agent_id"])))
        event_id = self.store.log_event(
            self.store.tick, "commons_moderation_applied",
            {"entry_id": entry_id, "moderator_agent_id": moderator_agent_id,
             "action": action, "reason": clean_reason}, phase="COMMONS",
            subject_type="agent", subject_id=moderator_agent_id, importance=1.0)
        moderation_id = self.store.insert(
            "commons_moderation_actions", entry_id=entry_id,
            moderator_agent_id=moderator_agent_id, action=action, reason=clean_reason,
            created_tick=self.store.tick, created_event_id=event_id, status="effective")
        self.store.commit()
        return {"ok": True, "moderation_action_id": moderation_id, "event_id": event_id}

    def appeal(self, actor_id: int, moderation_action_id: int, body: str) -> dict[str, Any]:
        self._living_agent(actor_id)
        action = self.store.query_one(
            "SELECT m.*,e.author_agent_id FROM commons_moderation_actions m "
            "JOIN commons_entries e ON e.id=m.entry_id WHERE m.id=?",
            (int(moderation_action_id),))
        if action is None:
            raise CommonsError(404, "moderation action not found")
        if int(action["author_agent_id"]) != actor_id:
            raise CommonsError(403, "only the entry author may appeal")
        text = str(body).strip()[:1000]
        if not text:
            raise CommonsError(400, "appeal body is required")
        try:
            appeal_id = self.store.insert(
                "commons_appeals", moderation_action_id=int(moderation_action_id),
                appellant_agent_id=actor_id, body_text=text, created_tick=self.store.tick,
                status="open")
        except Exception as exc:
            raise CommonsError(409, "an appeal already exists") from exc
        self.store.commit()
        return {"ok": True, "appeal_id": appeal_id, "status": "open"}

    def entry(self, entry_id: int) -> dict[str, Any]:
        row = self.store.query_one(
            "SELECT e.*,a.name AS author_name,c.slug AS community_slug,c.name AS community_name,"
            "(SELECT COUNT(*) FROM commons_reactions r WHERE r.entry_id=e.id AND r.status='active') "
            "AS reaction_count,(SELECT COUNT(*) FROM commons_entries q WHERE q.parent_entry_id=e.id "
            "AND q.status='published') AS reply_count FROM commons_entries e "
            "JOIN agents a ON a.id=e.author_agent_id LEFT JOIN commons_communities c "
            "ON c.id=e.community_id WHERE e.id=?", (int(entry_id),))
        if row is None:
            raise CommonsError(404, "entry not found")
        return self._entry_document(row)

    def overview(self, viewer_agent_id: int, *, limit: int = 30,
                 kind: str = "chronological") -> dict[str, Any]:
        communities = [dict(row) for row in self.store.query(
            "SELECT c.*,COUNT(CASE WHEN m.status='active' THEN 1 END) AS member_count "
            "FROM commons_communities c LEFT JOIN commons_memberships m ON m.community_id=c.id "
            "WHERE c.status='active' GROUP BY c.id ORDER BY c.id")]
        return {"profile": self.profile(viewer_agent_id), "communities": communities,
                "feed": self.feed(viewer_agent_id, kind=kind, limit=limit)}

    def public_overview(self, *, limit: int = 50,
                        kind: str = "chronological",
                        as_of_tick: int | None = None) -> dict[str, Any]:
        """Return the sanitized human Observatory projection without an exposure.

        Human dashboard rendering is not a simulated-agent feed delivery, so it
        must not create an impression, memory, belief update, or social tie.
        """
        if kind not in {"chronological", "hot"}:
            raise CommonsError(400, "invalid public feed kind")
        if as_of_tick is None:
            projection_tick = self.store.tick
        else:
            try:
                projection_tick = int(as_of_tick)
            except (TypeError, ValueError) as exc:
                raise CommonsError(
                    400, "commons projection tick must be an integer") from exc
        if projection_tick < 0 or projection_tick > self.store.tick:
            raise CommonsError(409, "commons projection tick is outside the recorded run")
        policy = self.store.query_one(
            "SELECT * FROM commons_feed_policies WHERE algorithm=? AND created_tick<=? "
            "ORDER BY created_tick DESC,version DESC,id DESC LIMIT 1",
            (kind, projection_tick))
        if policy is None:
            raise CommonsError(503, "feed policy unavailable")
        rows = self.store.query(
            "SELECT e.*,a.name AS author_name,a.occupation,a.alive,"
            "c.slug AS community_slug,c.name AS community_name,"
            "x.status AS connection_status,"
            "(SELECT m.reason FROM commons_moderation_actions m WHERE m.entry_id=e.id "
            "AND m.action='label' AND m.created_tick<=? "
            "ORDER BY m.created_tick DESC,m.id DESC LIMIT 1) AS historical_moderation_label,"
            "(SELECT COUNT(*) FROM commons_reactions r WHERE r.entry_id=e.id "
            "AND r.created_tick<=? AND COALESCE((SELECT json_extract(ev.payload_json,'$.status') "
            "FROM events ev WHERE ev.kind='commons_reaction_changed' AND ev.tick<=? "
            "AND CAST(json_extract(ev.payload_json,'$.entry_id') AS INTEGER)=r.entry_id "
            "AND CAST(json_extract(ev.payload_json,'$.agent_id') AS INTEGER)=r.agent_id "
            "AND json_extract(ev.payload_json,'$.reaction')=r.reaction "
            "ORDER BY ev.tick DESC,ev.id DESC LIMIT 1),'active')='active') AS reaction_count,"
            "(SELECT COUNT(*) FROM commons_entries q WHERE q.parent_entry_id=e.id "
            "AND q.created_tick<=? AND COALESCE((SELECT qm.action "
            "FROM commons_moderation_actions qm WHERE qm.entry_id=q.id "
            "AND qm.action IN ('hide','remove','restore') AND qm.created_tick<=? "
            "ORDER BY qm.created_tick DESC,qm.id DESC LIMIT 1),'restore')='restore') AS reply_count "
            "FROM commons_entries e JOIN agents a ON a.id=e.author_agent_id "
            "LEFT JOIN commons_communities c ON c.id=e.community_id "
            "LEFT JOIN external_agent_connections x ON x.actor_id=e.author_agent_id "
            "AND x.created_tick<=? "
            "WHERE e.created_tick<=? "
            "AND (a.died_tick IS NULL OR a.died_tick>?) "
            "AND (e.community_id IS NULL OR (c.visibility='public' AND c.created_tick<=?)) "
            "AND COALESCE((SELECT m.action FROM commons_moderation_actions m "
            "WHERE m.entry_id=e.id AND m.action IN ('hide','remove','restore') "
            "AND m.created_tick<=? ORDER BY m.created_tick DESC,m.id DESC LIMIT 1),"
            "'restore')='restore' ORDER BY e.id",
            (projection_tick, projection_tick, projection_tick, projection_tick,
             projection_tick, projection_tick, projection_tick, projection_tick,
             projection_tick, projection_tick))
        ranked: list[tuple[tuple[int, int], Any, dict[str, int]]] = []
        for row in rows:
            age = max(0, projection_tick - int(row["created_tick"]))
            components = {"reactions": int(row["reaction_count"]),
                          "replies": int(row["reply_count"]), "age_ticks": age}
            hot_score = components["reactions"] * 1000 + components["replies"] * 500 - age
            key = ((hot_score, int(row["id"])) if kind == "hot" else
                   (int(row["created_tick"]), int(row["id"])))
            ranked.append((key, row, components))
        ranked.sort(key=lambda item: item[0], reverse=True)
        candidate_ids = [int(item[1]["id"]) for item in ranked]
        candidate_hash = _canonical_hash({
            "policy_id": int(policy["id"]), "candidate_ids": sorted(candidate_ids)})
        entries = []
        author_ids: set[int] = set()
        for position, (_key, row, components) in enumerate(
                ranked[:max(1, min(int(limit), 100))], 1):
            author_id = int(row["author_agent_id"])
            author_ids.add(author_id)
            entry_document = self._entry_document(row)
            entry_document["status"] = "published"
            entry_document["moderation_label"] = row["historical_moderation_label"]
            entries.append({
                **entry_document,
                "position": position,
                "score_components": components,
                "author_connected_status": (
                    row["connection_status"]
                    if projection_tick == self.store.tick else None
                ),
                "causal_observatory": {
                    "source_kind": "commons_entry", "source_id": int(row["id"]),
                },
            })
        profiles = []
        if author_ids:
            placeholders = ",".join("?" for _ in author_ids)
            profile_rows = self.store.query(
                "SELECT p.*,a.occupation,1 AS alive,x.status AS connection_status,"
                "COALESCE((SELECT SUM((CASE json_extract(ev.payload_json,'$.reaction') "
                "WHEN 'insightful' THEN 2 WHEN 'like' THEN 1 WHEN 'agree' THEN 1 ELSE 0 END) "
                "* (CASE json_extract(ev.payload_json,'$.status') WHEN 'active' THEN 1 ELSE -1 END)) "
                "FROM events ev JOIN commons_entries ce ON ce.id="
                "CAST(json_extract(ev.payload_json,'$.entry_id') AS INTEGER) "
                "WHERE ev.kind='commons_reaction_changed' AND ev.tick<=? "
                "AND ce.author_agent_id=p.agent_id),0) AS historical_reputation,"
                "CASE WHEN EXISTS(SELECT 1 FROM commons_moderation_actions lm "
                "JOIN commons_entries le ON le.id=lm.entry_id "
                "WHERE le.author_agent_id=p.agent_id AND lm.action='limit_author' "
                "AND lm.created_tick<=?) THEN 'limited' ELSE 'active' END "
                "AS historical_profile_status "
                "FROM commons_profiles p JOIN agents a ON a.id=p.agent_id "
                "LEFT JOIN external_agent_connections x ON x.actor_id=p.agent_id "
                "AND x.created_tick<=? "
                f"WHERE p.agent_id IN ({placeholders}) "
                "AND (a.died_tick IS NULL OR a.died_tick>?) "
                "ORDER BY historical_reputation DESC,p.agent_id",
                (projection_tick, projection_tick, projection_tick,
                 *sorted(author_ids), projection_tick))
            profiles = []
            for row in profile_rows:
                document = self._profile_document(row)
                document["reputation"] = int(row["historical_reputation"] or 0)
                document["status"] = str(row["historical_profile_status"])
                if projection_tick != self.store.tick:
                    document["connected_agent_status"] = None
                profiles.append(document)
        communities = [dict(row) for row in self.store.query(
            "SELECT c.id,c.slug,c.name,c.description,c.visibility,c.created_tick,"
            "COUNT(CASE WHEN m.joined_tick<=? AND (m.updated_tick>? OR m.status='active') "
            "THEN 1 END) AS member_count "
            "FROM commons_communities c LEFT JOIN commons_memberships m "
            "ON m.community_id=c.id WHERE c.status='active' AND c.visibility='public' "
            "AND c.created_tick<=? GROUP BY c.id ORDER BY c.id",
            (projection_tick, projection_tick, projection_tick))]
        moderation = self.store.query_one(
            "SELECT COUNT(*) AS action_count,"
            "(SELECT COUNT(*) FROM commons_appeals WHERE created_tick<=? "
            "AND (resolved_tick IS NULL OR resolved_tick>?)) AS open_appeals "
            "FROM commons_moderation_actions WHERE created_tick<=?",
            (projection_tick, projection_tick, projection_tick))
        return {
            "version": "ae.commons.public.v1", "tick": projection_tick,
            "feed": {"feed_kind": kind, "candidate_set_hash": candidate_hash,
                     "policy": {"id": int(policy["id"]),
                                "key": str(policy["policy_key"]),
                                "version": int(policy["version"]),
                                "algorithm": str(policy["algorithm"])},
                     "entries": entries},
            "communities": communities, "profiles": profiles,
            "moderation": {"action_count": int(moderation["action_count"] or 0),
                           "open_appeals": int(moderation["open_appeals"] or 0)},
        }

    def act(self, actor_id: int, action: dict[str, Any], *, moderation_scope: bool = False) -> dict[str, Any]:
        if not isinstance(action, dict):
            raise CommonsError(400, "commons action must be an object")
        kind = str(action.get("type", ""))
        if kind == "post":
            return self.publish(actor_id, body=action.get("body", ""),
                                community_id=action.get("community_id"),
                                parent_entry_id=action.get("parent_entry_id"),
                                entry_type=str(action.get("entry_type", "post")),
                                claim_id=action.get("claim_id"))
        if kind == "react":
            return self.react(actor_id, int(action.get("entry_id", 0)),
                              str(action.get("reaction", "")),
                              active=bool(action.get("active", True)))
        if kind == "read":
            return self.read(actor_id, int(action.get("impression_id", 0)))
        if kind == "follow":
            return self.follow(actor_id, int(action.get("agent_id", 0)),
                               active=bool(action.get("active", True)))
        if kind == "join_community":
            return self.join_community(actor_id, int(action.get("community_id", 0)))
        if kind == "create_community":
            return self.create_community(actor_id, name=action.get("name", ""),
                                         description=action.get("description", ""),
                                         visibility=action.get("visibility", "public"))
        if kind == "moderate":
            if not moderation_scope:
                raise CommonsError(403, "moderation.act scope is required")
            return self.moderate(actor_id, int(action.get("entry_id", 0)),
                                 action=str(action.get("action", "")),
                                 reason=str(action.get("reason", "")))
        if kind == "appeal":
            return self.appeal(actor_id, int(action.get("moderation_action_id", 0)),
                               str(action.get("body", "")))
        raise CommonsError(400, "unsupported commons action")

    def _living_agent(self, agent_id: int):
        row = self.store.query_one("SELECT * FROM agents WHERE id=?", (int(agent_id),))
        if row is None:
            raise CommonsError(404, "agent not found")
        if not bool(row["alive"]):
            raise CommonsError(409, "agent is not living")
        return row

    def _community(self, community_id: int):
        row = self.store.query_one(
            "SELECT * FROM commons_communities WHERE id=? AND status='active'",
            (int(community_id),))
        if row is None:
            raise CommonsError(404, "community not found")
        return row

    def _entry(self, entry_id: int):
        row = self.store.query_one("SELECT * FROM commons_entries WHERE id=?", (int(entry_id),))
        if row is None:
            raise CommonsError(404, "entry not found")
        return row

    def _is_member(self, agent_id: int, community_id: int) -> bool:
        return self.store.query_one(
            "SELECT 1 FROM commons_memberships WHERE community_id=? AND agent_id=? "
            "AND status='active'", (community_id, agent_id)) is not None

    def _is_moderator(self, agent_id: int, community_id: int) -> bool:
        return self.store.query_one(
            "SELECT 1 FROM commons_memberships WHERE community_id=? AND agent_id=? "
            "AND status='active' AND role IN ('moderator','owner')",
            (community_id, agent_id)) is not None

    def _strengthen_social_tie(self, first: int, second: int) -> None:
        if first == second:
            return
        lo, hi = min(first, second), max(first, second)
        row = self.store.query_one(
            "SELECT weight FROM social_ties WHERE agent_a=? AND agent_b=?", (lo, hi))
        if row is None:
            self.store.insert("social_ties", agent_a=lo, agent_b=hi, weight=0.05)
        else:
            self.store.execute(
                "UPDATE social_ties SET weight=? WHERE agent_a=? AND agent_b=?",
                (min(1.0, float(row["weight"]) + 0.01), lo, hi))

    @staticmethod
    def _entry_document(row) -> dict[str, Any]:
        keys = set(row.keys())
        return {
            "id": int(row["id"]), "community_id": row["community_id"],
            "community_slug": row["community_slug"] if "community_slug" in keys else None,
            "community_name": row["community_name"] if "community_name" in keys else None,
            "author_agent_id": int(row["author_agent_id"]),
            "author_name": row["author_name"] if "author_name" in keys else None,
            "entry_type": str(row["entry_type"]), "root_entry_id": row["root_entry_id"],
            "parent_entry_id": row["parent_entry_id"], "body": str(row["body_text"]),
            "claim_id": row["claim_id"], "created_tick": int(row["created_tick"]),
            "status": str(row["status"]), "moderation_label": row["moderation_label"],
            "reaction_count": int(row["reaction_count"]) if "reaction_count" in keys else 0,
            "reply_count": int(row["reply_count"]) if "reply_count" in keys else 0,
        }

    def _profile_document(self, row) -> dict[str, Any]:
        keys = set(row.keys())
        return {
            "agent_id": int(row["agent_id"]), "display_name": str(row["display_name"]),
            "biography": str(row["biography"]), "reputation": int(row["reputation"]),
            "status": str(row["status"]),
            "occupation": row["occupation"] if "occupation" in keys else None,
            "alive": bool(row["alive"]) if "alive" in keys else True,
            "connected_agent_status": (
                row["connection_status"] if "connection_status" in keys else None),
        }
