"""Newsroom + evening conversations (PRD R5, TECH-SPEC §10).

Reporters draw ONLY on true sim events (the tick's event digest, filtered by a
newsworthiness heuristic); framing/selection is theirs (scripted or LLM per
routing). Stories cite source_event_ids so coverage can be audited against ground
truth (distortion index). Conversations pair socially-connected agents; lines
heard become observations → memory → beliefs. This is the rumor medium.
"""
from __future__ import annotations

import json
from typing import Optional

from engine.core import Economy
from engine.store import load_json
from llm.gateway import Gateway, LLMRequest
from agents.memory import Memory


class Newsroom:
    def __init__(self, economy: Economy, gateway: Gateway, config: dict, shocks):
        self.e = economy
        self.store = economy.store
        self.gw = gateway
        self.config = config
        self.shocks = shocks
        self.outlets = config.get("outlets", [
            {"id": 1, "name": "The Ledger", "slant": "pro-market-sensational"},
            {"id": 2, "name": "Commons Dispatch", "slant": "cautious-pro-labor"},
        ])

    async def publish(self, tick: int) -> list[dict]:
        events = self._salient_events(tick)
        if not events:
            return []
        directives = self.shocks.active_slant_directives(tick) if self.shocks else {}
        articles = []
        for outlet in self.outlets:
            # Two-stage desk (TECH-SPEC §10): the reporter drafts 2–4 candidate
            # stories from true events; the editor selects and frames per slant.
            drafts = await self._report_stories(tick, outlet, events)
            art = await self._write_story(tick, outlet, events, directives.get(outlet["id"]),
                                          drafts=drafts)
            if art and art.get("headline"):
                aid = self.store.insert(
                    "news_articles", tick=tick, outlet_id=outlet["id"], outlet_name=outlet["name"],
                    headline=art["headline"][:200], body=art.get("body", "")[:2000],
                    slant_tags=json.dumps(art.get("slant_tags", [outlet["slant"]])),
                    source_event_ids=json.dumps(art.get("source_event_ids", [])),
                    tone=float(art.get("tone", 0.0)), truthful=1)
                self.store.log_event(tick, "news_published", {
                    "article_id": aid, "outlet_id": outlet["id"], "outlet": outlet["name"],
                    "headline": art["headline"], "tone": art.get("tone", 0.0)},
                    phase="NEWSROOM", importance=1.5)
                articles.append(art)
        return articles

    def _salient_events(self, tick: int) -> list[dict]:
        rows = self.store.query(
            "SELECT * FROM events WHERE tick=? AND importance>=1.5 "
            "AND kind NOT IN ('news_published','metrics_snapshot') ORDER BY importance DESC, id LIMIT 12",
            (tick,))
        out = []
        for r in rows:
            out.append({"id": int(r["id"]), "kind": r["kind"],
                        "payload": load_json(r["payload_json"], {}) or {},
                        "importance": float(r["importance"])})
        return out

    def _desk_agent(self, role: str, outlet_id: int) -> Optional[int]:
        row = self.store.query_one(
            "SELECT id FROM agents WHERE role=? AND alive=1 "
            "AND json_extract(personality_json,'$.outlet_id')=?", (role, outlet_id))
        return int(row["id"]) if row else None

    async def _report_stories(self, tick: int, outlet: dict, events: list[dict]) -> list[dict]:
        """Reporter stage: draft 2–4 candidate stories from the day's true events."""
        context = {"tick": tick, "outlet": outlet, "salient_events": events,
                   "rng_seed": tick * 37 + outlet["id"]}
        system = ("You are a reporter in a simulated economy. From the given TRUE events draft "
                  "2-4 short candidate stories as JSON: {\"stories\": [{\"headline\":..., "
                  "\"body\":..., \"tone\": -1..1, \"kind\":..., \"source_event_ids\":[...]}]}. "
                  "Report only what the events support; no invented facts.")
        req = LLMRequest(role="reporter", purpose="reporter", system=system,
                         user=json.dumps({"events": events})[:3000], context=context,
                         agent_id=self._desk_agent("reporter", outlet["id"]),
                         tick=tick, max_tokens=500)
        resp = await self.gw.complete(req)
        env = resp.parsed if isinstance(resp.parsed, dict) else {}
        stories = env.get("stories", [])
        return stories if isinstance(stories, list) else []

    async def _write_story(self, tick: int, outlet: dict, events: list[dict],
                           directive: Optional[str], drafts: Optional[list[dict]] = None
                           ) -> Optional[dict]:
        """Editor stage: select one draft and frame it per the outlet's slant.
        Falls back to composing directly from events when the reporter came back
        empty (robustness with real LLMs)."""
        context = {"tick": tick, "outlet": outlet, "salient_events": events,
                   "drafts": drafts or [], "directive": directive,
                   "rng_seed": tick * 31 + outlet["id"]}
        user = json.dumps({"outlet": outlet, "drafts": drafts or [], "events": events,
                           "directive": directive})[:3000]
        system = ("You are the editor of a simulated-economy news outlet. Pick the ONE candidate "
                  "story that best fits your outlet's slant (or compose from the events if no "
                  "drafts), then frame it. Reply as JSON: {\"headline\":..., \"body\":..., "
                  "\"tone\": -1..1, \"slant_tags\":[...], \"source_event_ids\":[...]}. "
                  "Only use the given true events; framing and selection reflect your slant.")
        req = LLMRequest(role="editor", purpose="newsroom", system=system, user=user,
                         context=context, agent_id=self._desk_agent("editor", outlet["id"]),
                         tick=tick, max_tokens=400)
        resp = await self.gw.complete(req)
        art = resp.parsed if isinstance(resp.parsed, dict) else {}
        if directive and art.get("headline"):
            # A slant directive skews tone negative/positive per its wording; scripted
            # policy can't parse text, so nudge tone toward alarm when directed.
            art["tone"] = float(art.get("tone", 0.0)) - 0.3
            art["slant_tags"] = list(art.get("slant_tags", [])) + ["directed"]
        return art


class Conversations:
    def __init__(self, economy: Economy, gateway: Gateway, config: dict):
        self.e = economy
        self.store = economy.store
        self.gw = gateway
        self.config = config
        self.mem = Memory(self.store)
        self.turns = int(config.get("conversations", {}).get("turns", 3))

    async def evening(self, tick: int) -> int:
        pairs = self._sample_pairs(tick, self.gw.governor.conversation_pairs())
        count = 0
        for a, b in pairs:
            await self._converse(tick, a, b)
            count += 1
        return count

    def _sample_pairs(self, tick: int, k: int) -> list[tuple[int, int]]:
        if k <= 0:
            return []
        ties = self.store.query(
            "SELECT t.agent_a, t.agent_b, t.weight FROM social_ties t "
            "JOIN agents x ON x.id=t.agent_a JOIN agents y ON y.id=t.agent_b "
            "WHERE x.alive=1 AND y.alive=1")
        if not ties:
            return []
        # Weight by tie strength + event salience (agents touched by big events talk).
        salient = {int(r["agent_id"]) for r in self.store.query(
            "SELECT DISTINCT agent_id FROM memories WHERE tick>=? AND importance>=2.5", (tick - 1,))}
        weighted = []
        for t in ties:
            w = float(t["weight"])
            if int(t["agent_a"]) in salient or int(t["agent_b"]) in salient:
                w *= 3.0
            weighted.append((w, int(t["agent_a"]), int(t["agent_b"])))
        # Deterministic weighted sample without replacement via engine PRNG.
        chosen: list[tuple[int, int]] = []
        pool = weighted[:]
        used: set[int] = set()
        while pool and len(chosen) < k:
            total = sum(w for w, _, _ in pool)
            r = self.e.prng.random() * total
            acc = 0.0
            pick = pool[-1]
            for item in pool:
                acc += item[0]
                if r <= acc:
                    pick = item
                    break
            pool.remove(pick)
            _, a, b = pick
            if a in used or b in used:
                continue
            used.add(a); used.add(b)
            chosen.append((a, b))
        return chosen

    async def _converse(self, tick: int, a_id: int, b_id: int) -> None:
        conv_id = self.store.insert("conversations", tick=tick,
                                    participant_ids=json.dumps([a_id, b_id]), topic=None)
        names = {aid: self.store.scalar("SELECT name FROM agents WHERE id=?", (aid,), default="?")
                 for aid in (a_id, b_id)}
        rumors = {aid: self._rumor_held(aid, tick) for aid in (a_id, b_id)}
        shared_topic = self._shared_topic(tick)
        seq = 0
        for turn in range(self.turns):
            speaker, listener = (a_id, b_id) if turn % 2 == 0 else (b_id, a_id)
            context = {"tick": tick, "speaker_id": speaker,
                       "partner_name": names[listener],
                       "speaker_rumor_bank": rumors[speaker],
                       "shared_topic": shared_topic,
                       "rng_seed": tick * 1009 + speaker * 13 + turn}
            schema = '{"text":"brief natural sentence","rumor_bank":null}'
            req = LLMRequest(
                role="citizen", purpose="conversation",
                system=(
                    "Write one brief in-world conversational sentence from the speaker "
                    "to the named partner. Respond ONLY with JSON matching " + schema
                    + ". Set rumor_bank to an integer from speaker_rumor_bank only when "
                      "the speaker shares that rumor; otherwise use null."),
                user=json.dumps(context)[:800], context=context,
                agent_id=speaker, tick=tick, max_tokens=120)
            resp = await self.gw.complete(req, schema_hint=schema)
            env = resp.parsed if isinstance(resp.parsed, dict) else {}
            text = str(env.get("text", "")).strip()[:300]
            if not text:
                continue
            self.store.insert("messages", conv_id=conv_id, tick=tick, agent_id=speaker,
                              text=text, seq=seq)
            seq += 1
            # The listener hears the line → observation (rumor propagation medium).
            ents = ["conversation", f"agent:{speaker}"]
            rumor_bank = env.get("rumor_bank")
            importance = 1.0
            if rumor_bank is not None:
                ents.append(f"rumor_bank:{int(rumor_bank)}")
                ents.append(f"bank:{int(rumor_bank)}")
                importance = 3.0
                rumors[listener] = int(rumor_bank)  # they may pass it on next turn
            self.mem.observe(listener, tick, f"{names[speaker]} said: {text}",
                             importance=importance, entities=ents)
        self.store.log_event(tick, "conversation", {
            "conv_id": conv_id, "participants": [a_id, b_id], "turns": seq},
            phase="EVENING", importance=0.5)

    def _rumor_held(self, agent_id: int, tick: int) -> Optional[int]:
        rows = self.store.query(
            "SELECT entities_json FROM memories WHERE agent_id=? AND tick>=? AND kind='observation'",
            (agent_id, tick - 3))
        for r in rows:
            for e in load_json(r["entities_json"], []) or []:
                if isinstance(e, str) and e.startswith("rumor_bank:"):
                    return int(e.split(":")[1])
        return None

    def _shared_topic(self, tick: int) -> Optional[str]:
        row = self.store.query_one(
            "SELECT headline FROM news_articles WHERE tick>=? ORDER BY id DESC LIMIT 1", (tick - 1,))
        return row["headline"] if row else None
