"""Newsroom + evening conversations (PRD R5, TECH-SPEC §10).

Reporters draw ONLY on true sim events (the tick's event digest, filtered by a
newsworthiness heuristic); framing/selection is theirs (scripted or LLM per
routing). Stories cite source_event_ids so coverage can be audited against ground
truth (distortion index). Conversations pair socially-connected agents; lines
heard become observations → memory → beliefs. This is the rumor medium.
"""
from __future__ import annotations

from collections import deque
from difflib import SequenceMatcher
import json
import re
from typing import Optional

from engine.core import Economy
from engine.store import load_json
from llm.gateway import Gateway, LLMRequest
from agents.memory import Memory
from agents.policies import conversation_turn


DEFAULT_CONVERSATION_THEMES = [
    "household budgets and the price of essentials",
    "job security, hiring, and workplace changes",
    "wages and the cost of living",
    "saving, borrowing, and confidence in local banks",
    "local businesses, inventory, and changing prices",
    "health costs and financial resilience",
    "how market moves affect ordinary households",
]


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
        pending = []
        for outlet in self.outlets:
            if self.store.query_one(
                    "SELECT id FROM news_articles WHERE tick=? AND outlet_id=?",
                    (tick, outlet["id"])):
                continue
            # Two-stage desk (TECH-SPEC §10): the reporter drafts 2–4 candidate
            # stories from true events; the editor selects and frames per slant.
            drafts = await self._report_stories(tick, outlet, events)
            art = await self._write_story(tick, outlet, events, directives.get(outlet["id"]),
                                          drafts=drafts)
            if art and art.get("headline"):
                pending.append((outlet, art))
        articles = []
        with self.store.savepoint(f"newsroom_{tick}"):
            for outlet, art in pending:
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
        self._recent_limit = int(
            config.get("conversations", {}).get("recent_utterance_limit", 12))
        self._recent_per_source = max(2, self._recent_limit // 3)
        self._recent_global: deque[str] = deque(maxlen=self._recent_per_source)
        self._recent_by_agent: dict[int, deque[str]] = {}
        self._recent_by_topic: dict[str, deque[str]] = {}
        self._used_line_keys: set[str] = set()
        for row in self.store.query(
                "SELECT m.agent_id, m.text, c.topic FROM messages m "
                "JOIN conversations c ON c.id=m.conv_id ORDER BY m.id"):
            self._remember_line(int(row["agent_id"]), row["topic"], str(row["text"]))

    def plan_pairs(self, tick: int) -> list[tuple[int, int]]:
        return self._sample_pairs(tick, self.gw.governor.conversation_pairs())

    async def evening(self, tick: int,
                      pairs: Optional[list[tuple[int, int]]] = None) -> int:
        pairs = self.plan_pairs(tick) if pairs is None else pairs
        count = 0
        for topic_slot, (a, b) in enumerate(pairs):
            await self._converse(tick, a, b, topic_slot=topic_slot)
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

    async def _converse(self, tick: int, a_id: int, b_id: int,
                        *, topic_slot: int = 0) -> None:
        participant_ids = json.dumps([a_id, b_id])
        if self.store.query_one(
                "SELECT id FROM conversations WHERE tick=? AND participant_ids=?",
                (tick, participant_ids)):
            return
        names = {aid: self.store.scalar("SELECT name FROM agents WHERE id=?", (aid,), default="?")
                 for aid in (a_id, b_id)}
        profiles = {
            aid: dict(self.store.query_one(
                "SELECT name, occupation, age, health, kind FROM agents WHERE id=?", (aid,)))
            for aid in (a_id, b_id)
        }
        rumors = {aid: self._rumor_held(aid, tick) for aid in (a_id, b_id)}
        shared_topic = self._shared_topic(tick, a_id, b_id, topic_slot=topic_slot)
        transcript = []
        for turn in range(self.turns):
            speaker, listener = (a_id, b_id) if turn % 2 == 0 else (b_id, a_id)
            recent_utterances = self._recent_utterances(speaker, shared_topic)
            conversation_so_far = [line["text"] for line in transcript]
            context = {"tick": tick, "speaker_id": speaker,
                       "partner_name": names[listener],
                       "speaker_profile": profiles[speaker],
                       "speaker_rumor_bank": rumors[speaker],
                       "shared_topic": shared_topic,
                       "turn_index": turn,
                       "conversation_so_far": conversation_so_far,
                       "recent_utterances": recent_utterances,
                       "avoid_texts": recent_utterances + conversation_so_far,
                       "rng_seed": tick * 1009 + speaker * 13 + turn}
            schema = '{"text":"brief natural sentence","rumor_bank":null}'
            req = LLMRequest(
                role="citizen", purpose="conversation",
                system=(
                    "Continue a natural in-world conversation with one brief sentence from "
                    "the speaker to the named partner. Use the shared topic when present, "
                    "and treat the supplied JSON context as the entire factual world. Do not "
                    "invent laws, websites, contracts, lawsuits, investigations, client lists, "
                    "relationships, institutions, or off-screen events. Facts not present in "
                    "the context are unknown; express uncertainty instead of filling gaps. "
                    "Use a cautious modal statement (may, might, could, seems) or a question. "
                    "Do not use first-person pronouns or narrate anecdotes, employer details, "
                    "possessions, private contacts, or past experiences. A general concern based "
                    "on the supplied occupation is allowed, but an unsupported backstory is not. "
                    "Do not repeat or closely paraphrase conversation_so_far, "
                    "recent_utterances, or avoid_texts. If the previous line asked a "
                    "question, respond to it instead of asking the same question again. "
                    "A question is optional; prefer a concrete reaction or personal impact. "
                    "Respond ONLY with JSON matching " + schema
                    + ". Set rumor_bank to an integer from speaker_rumor_bank only when "
                    "the speaker shares that rumor; otherwise use null."),
                user=json.dumps({
                    key: value for key, value in context.items()
                    if key != "avoid_texts"
                })[:2400], context=context,
                agent_id=speaker, tick=tick, max_tokens=120)
            resp = await self.gw.complete(req, schema_hint=schema)
            env = resp.parsed if isinstance(resp.parsed, dict) else {}
            text = str(env.get("text", "")).strip()[:300]
            if not text:
                continue
            avoid_texts = recent_utterances + conversation_so_far
            repeats_question = (
                "?" in text and bool(conversation_so_far)
                and "?" in conversation_so_far[-1]
            )
            if (repeats_question or self._has_ungrounded_detail(text)
                    or self._previously_said(text, avoid_texts)):
                fallback_context = dict(context)
                fallback_context["avoid_texts"] = list(avoid_texts)
                for attempt in range(1, 10):
                    fallback_context["rng_seed"] = (
                        int(context["rng_seed"]) + 104729 * attempt)
                    fallback = conversation_turn(fallback_context)
                    candidate = str(fallback.get("text", "")).strip()[:300]
                    if not self._previously_said(candidate, avoid_texts):
                        text = candidate
                        env = fallback
                        break
                    fallback_context["avoid_texts"].append(candidate)
                else:
                    text = f"{candidate.rstrip()} This feels different on day {tick}."[:300]
                    env = fallback
            # The listener hears the line → observation (rumor propagation medium).
            ents = ["conversation", f"agent:{speaker}"]
            rumor_bank = env.get("rumor_bank")
            importance = 1.0
            if rumor_bank is not None:
                ents.append(f"rumor_bank:{int(rumor_bank)}")
                ents.append(f"bank:{int(rumor_bank)}")
                importance = 3.0
                rumors[listener] = int(rumor_bank)  # they may pass it on next turn
            transcript.append({
                "speaker": speaker, "listener": listener, "text": text,
                "importance": importance, "entities": ents,
            })
        with self.store.savepoint(f"conversation_{tick}_{a_id}_{b_id}"):
            conv_id = self.store.insert(
                "conversations", tick=tick, participant_ids=participant_ids,
                topic=shared_topic)
            for seq, line in enumerate(transcript):
                self.store.insert(
                    "messages", conv_id=conv_id, tick=tick,
                    agent_id=line["speaker"], text=line["text"], seq=seq)
                self.mem.observe(
                    line["listener"], tick,
                    f"{names[line['speaker']]} said: {line['text']}",
                    importance=line["importance"], entities=line["entities"])
            self.store.log_event(tick, "conversation", {
                "conv_id": conv_id, "participants": [a_id, b_id],
                "turns": len(transcript)},
                phase="EVENING", importance=0.5)
        for line in transcript:
            self._remember_line(int(line["speaker"]), shared_topic, line["text"])

    def _rumor_held(self, agent_id: int, tick: int) -> Optional[int]:
        rows = self.store.query(
            "SELECT entities_json FROM memories WHERE agent_id=? AND tick>=? AND kind='observation'",
            (agent_id, tick - 3))
        for r in rows:
            for e in load_json(r["entities_json"], []) or []:
                if isinstance(e, str) and e.startswith("rumor_bank:"):
                    return int(e.split(":")[1])
        return None

    def _recent_utterances(self, agent_id: int, topic: Optional[str]) -> list[str]:
        """Return compact no-repeat context from the speaker and this topic."""
        texts = list(reversed(self._recent_global))
        texts.extend(reversed(self._recent_by_agent.get(agent_id, ())))
        if topic:
            texts.extend(reversed(self._recent_by_topic.get(topic.lower(), ())))
        unique: list[str] = []
        seen: set[str] = set()
        for text in texts:
            key = self._line_key(text)
            if key and key not in seen:
                seen.add(key)
                unique.append(text)
        return unique[:self._recent_limit]

    def _remember_line(self, agent_id: int, topic: Optional[str], text: str) -> None:
        self._used_line_keys.add(self._line_key(text))
        self._recent_global.append(text)
        agent_lines = self._recent_by_agent.setdefault(
            agent_id, deque(maxlen=self._recent_per_source))
        agent_lines.append(text)
        if topic:
            topic_lines = self._recent_by_topic.setdefault(
                str(topic).lower(), deque(maxlen=self._recent_per_source))
            topic_lines.append(text)

    @staticmethod
    def _line_key(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    @classmethod
    def _too_similar(cls, text: str, prior_lines: list[str]) -> bool:
        key = cls._line_key(text)
        if not key:
            return False
        for prior in prior_lines:
            prior_key = cls._line_key(prior)
            if key == prior_key:
                return True
            if min(len(key), len(prior_key)) >= 24:
                if SequenceMatcher(None, key, prior_key).ratio() >= 0.90:
                    return True
        return False

    @staticmethod
    def _has_ungrounded_detail(text: str) -> bool:
        """Allow only cautious, impersonal provider lines grounded in supplied state."""
        patterns = (
            r"\b(linkedin|attorneys?|arbitration|non[- ]?compete|lawsuits?|litigat\w*|"
            r"legal team|client list|discovery)\b",
            r"\b(last (?:week|month|year)|years? ago|yesterday|next term|two miles|"
            r"since we last)\b",
            r"\b(?:i|we) (?:know|heard|saw|started|kept|have|had|used to|work at|"
            r"spoke to|sat down)\b",
            r"\bmy (?:contract|employer|school|shop|clients?|suppliers?|books?|receipts?|"
            r"coworkers?|manager|neighbou?r|family|friends?|portfolio|pipeline)\b",
            r"\b(?:people|someone) (?:i know|over at|on the inside)\b",
            r"\b(?:the school|the shop|the office|the factory)\b",
            r"\b(?:had to know|knew those|welcome mat|paperwork)\b",
        )
        lowered = text.lower()
        if any(re.search(pattern, lowered) for pattern in patterns):
            return True
        if re.search(
                r"\b(i|i'm|i've|i'd|i'll|me|my|mine|we|we're|we've|we'd|we'll|"
                r"us|our|ours)\b", lowered):
            return True
        return not bool(re.search(
            r"\?|\b(may|might|could|seems?|appears?|perhaps|possibly|uncertain|"
            r"risk|worry|wonder|likely)\b", lowered))

    def _previously_said(self, text: str, prior_lines: list[str]) -> bool:
        if self._too_similar(text, prior_lines):
            return True
        return self._line_key(text) in self._used_line_keys

    def _shared_topic(self, tick: int, a_id: int | None = None,
                      b_id: int | None = None, *, topic_slot: int = 0) -> Optional[str]:
        """Rotate recent headlines across pairs instead of saturating a day with one topic."""
        cfg = self.config.get("conversations", {})
        lookback = max(1, int(cfg.get("topic_lookback_ticks", 3)))
        limit = max(2, int(cfg.get("topic_pool_size", 12)))
        rows = self.store.query(
            "SELECT headline, source_event_ids FROM news_articles WHERE tick>=? "
            "ORDER BY tick DESC, id DESC LIMIT ?",
            (tick - lookback + 1, limit))
        topics: list[str] = []
        seen: set[str] = set()
        seen_sources: set[tuple[int, ...]] = set()
        for row in rows:
            topic = str(row["headline"] or "").strip()
            key = topic.lower()
            sources = load_json(row["source_event_ids"], []) or []
            source_key = tuple(sorted(int(source) for source in sources))
            if source_key and source_key in seen_sources:
                continue
            if topic and key not in seen:
                seen.add(key)
                if source_key:
                    seen_sources.add(source_key)
                topics.append(topic)
        themes = cfg.get("themes", DEFAULT_CONVERSATION_THEMES)
        theme_topics: list[str] = []
        for theme_value in themes:
            theme = str(theme_value or "").strip()
            key = theme.lower()
            if theme and key not in seen:
                seen.add(key)
                theme_topics.append(theme)
        if theme_topics:
            daily_advance = max(1, int(
                self.config.get("budget", {}).get("conversation_pairs", 1)))
            theme_offset = (max(0, tick - 1) * daily_advance) % len(theme_topics)
            topics.extend(theme_topics[theme_offset:] + theme_topics[:theme_offset])
        if not topics:
            return None

        if a_id is not None and b_id is not None:
            pair_json = (json.dumps([a_id, b_id]), json.dumps([b_id, a_id]))
            prior_rows = self.store.query(
                "SELECT topic FROM conversations WHERE participant_ids IN (?, ?) "
                "AND tick>=? AND topic IS NOT NULL ORDER BY tick DESC",
                (pair_json[0], pair_json[1], tick - lookback))
            prior = {str(row["topic"]).lower() for row in prior_rows}
            fresh = [topic for topic in topics if topic.lower() not in prior]
            if fresh:
                topics = fresh

        return topics[topic_slot % len(topics)]
