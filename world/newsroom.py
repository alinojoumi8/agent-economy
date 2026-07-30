"""Newsroom + evening conversations (PRD R5, TECH-SPEC §10).

Reporters draw ONLY on true sim events (the tick's event digest, filtered by a
newsworthiness heuristic); framing/selection is theirs (scripted or LLM per
routing). Stories cite source_event_ids so coverage can be audited against ground
truth (distortion index). Conversations pair socially-connected agents; lines
heard become observations → memory → beliefs. This is the rumor medium.
"""
from __future__ import annotations

from collections import deque
import json
import math
import re
from typing import Optional

from engine.core import Economy
from engine.store import load_json
from llm.gateway import (
    Gateway,
    LLMRequest,
    ReplayReferenceError,
    sanitize_provider_text,
)
from agents.memory import Memory
from agents.policies import conversation_turn
from world.event_visibility import (
    PUBLIC_REPORTABLE_EVENT_KINDS,
    public_event_payload,
)


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
        # Missing means historical behavior. Fresh maintained profiles opt in
        # explicitly so stored runs replay with the newsroom contract they had
        # when they were created.
        self.daily_news_required = bool(
            config.get("information", {}).get("daily_news_required", False))
        self.outlets = config.get("outlets", [
            {"id": 1, "name": "The Ledger", "slant": "pro-market-sensational"},
            {"id": 2, "name": "Commons Dispatch", "slant": "cautious-pro-labor"},
        ])

    async def publish(self, tick: int) -> list[dict]:
        events = self._salient_events(tick)
        if not events and self.daily_news_required:
            events = self._daily_events(tick)
        if not events and self.daily_news_required:
            # A quiet day is itself a true, engine-observed fact. Persist it
            # before the desks write so every daily brief has an auditable
            # source event instead of inventing activity that did not occur.
            event_id = self.store.log_event(
                tick, "quiet_day", {
                    "summary": "No reportable economic event occurred before the newsroom phase.",
                }, phase="NEWSROOM", importance=0.25)
            events = [{
                "id": event_id, "kind": "quiet_day",
                "payload": {
                    "summary": "No reportable economic event occurred before the newsroom phase.",
                },
                "importance": 0.25,
            }]
        if not events:
            return []
        directives = self.shocks.active_slant_directives(tick) if self.shocks else {}
        # Drafts and the pending article batch are ephemeral. Replay therefore
        # admits the complete newsroom phase atomically: a later desk failure
        # must retry every source row used to rebuild the same pending batch.
        with self.gw.replay_admission(f"newsroom_publish_{tick}"):
            pending = []
            for outlet in self.outlets:
                if self.store.query_one(
                        "SELECT id FROM news_articles WHERE tick=? AND outlet_id=?",
                        (tick, outlet["id"])):
                    continue
                # Two-stage desk (TECH-SPEC §10): the reporter drafts 2–4
                # candidate stories; the editor selects and frames per slant.
                drafts = await self._report_stories(tick, outlet, events)
                art = await self._write_story(
                    tick, outlet, events, directives.get(outlet["id"]),
                    drafts=drafts)
                if art:
                    pending.append((outlet, art))
            articles = []
            with self.store.savepoint(f"newsroom_{tick}"):
                for outlet, art in pending:
                    aid = self.store.insert(
                        "news_articles", tick=tick, outlet_id=outlet["id"],
                        outlet_name=outlet["name"], headline=art["headline"][:200],
                        body=art.get("body", "")[:2000],
                        slant_tags=json.dumps(
                            art.get("slant_tags", [outlet["slant"]])),
                        source_event_ids=json.dumps(
                            art.get("source_event_ids", [])),
                        tone=float(art.get("tone", 0.0)), truthful=1)
                    # Mirror the article into the v2 claim/exposure economy.
                    # This adapter never fabricates a second source of truth.
                    self.e.information.register_news_article(
                        tick, aid, int(outlet["id"]), art["headline"],
                        art.get("body", ""),
                        [int(item) for item in art.get("source_event_ids", [])],
                        float(art.get("tone", 0.0)),
                        author_agent_id=self._desk_agent(
                            "editor", int(outlet["id"])),
                        slant=float(art.get("slant_score", 0.0)))
                    self.store.log_event(tick, "news_published", {
                        "article_id": aid, "outlet_id": outlet["id"],
                        "outlet": outlet["name"], "headline": art["headline"],
                        "tone": art.get("tone", 0.0)},
                        phase="NEWSROOM", importance=1.5)
                    articles.append(art)
            return articles

    def _daily_events(self, tick: int) -> list[dict]:
        """Return true events for a low-salience daily brief.

        The normal desk still leads with material events. This path exists only
        for profiles that promise daily publication and never reaches backward
        to another tick, so a story cannot silently recycle yesterday's news.
        """
        kinds = tuple(sorted(PUBLIC_REPORTABLE_EVENT_KINDS))
        placeholders = ",".join("?" for _ in kinds)
        rows = self.store.query(
            f"SELECT * FROM events WHERE tick=? AND kind IN ({placeholders}) "
            "ORDER BY importance DESC, id LIMIT 12", (tick, *kinds))
        return [{
            "id": int(row["id"]), "tick": int(row["tick"]), "kind": row["kind"],
            "payload": public_event_payload(
                row["kind"], load_json(row["payload_json"], {}) or {}),
            "importance": float(row["importance"]),
        } for row in rows]

    def _logical_source_event_id(self, source_event_id: int,
                                 events: list[dict]) -> Optional[int]:
        """Resolve a recorded replay event ID to this database's local ID.

        Event IDs are SQLite surrogates. Operational participant events can
        shift them between a source run and an otherwise exact replay, so a
        recorded newsroom response must be matched by deterministic event
        contents before its citation is accepted locally. Ambiguous or missing
        matches fail closed.
        """
        replay_conn = getattr(self.gw, "replay_conn", None)
        if replay_conn is None:
            return source_event_id if any(
                int(event["id"]) == source_event_id for event in events) else None

        def replay_reference_error(reason: str):
            raise ReplayReferenceError(
                f"newsroom source event {source_event_id}: {reason}")

        source = replay_conn.execute(
            "SELECT tick,kind,payload_json,importance FROM events WHERE id=?",
            (source_event_id,)).fetchone()
        if source is None:
            # Preserve the live contract: a model-invented citation was already
            # invalid in the source run, so replay must take the same brief
            # fallback instead of treating it as replay divergence.
            return None

        # Use the event digest that was actually persisted with the recorded
        # editor request.  Rebuilding it from the finalized source event table
        # is unsafe because later same-tick events were not visible to the desk.
        source_digests: dict[str, list[dict]] = {}
        source_calls = replay_conn.execute(
            "SELECT request_json FROM llm_calls WHERE tick=? AND purpose='newsroom' "
            "ORDER BY id", (int(source["tick"]),)).fetchall()
        for call in source_calls:
            request = load_json(call["request_json"], {}) or {}
            context = request.get("context", {}) if isinstance(request, dict) else {}
            digest = context.get("salient_events", []) \
                if isinstance(context, dict) else []
            if not isinstance(digest, list) or not all(
                    isinstance(event, dict) for event in digest):
                continue
            if not any(type(event.get("id")) is int
                       and int(event["id"]) == source_event_id
                       for event in digest):
                continue
            key = json.dumps(
                digest, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False)
            source_digests[key] = digest
        if len(source_digests) != 1:
            # Existing but out-of-prompt citations are also invalid model input,
            # not evidence that a valid source occurrence disappeared locally.
            return None

        source_digest = next(iter(source_digests.values()))
        source_payload = public_event_payload(
            source["kind"], load_json(source["payload_json"], {}) or {})
        source_candidates = []
        for event in source_digest:
            event_id = event.get("id")
            try:
                same_tick = (
                    int(event.get("tick", source["tick"])) == int(source["tick"]))
                same_importance = (
                    float(event.get("importance")) == float(source["importance"]))
            except (TypeError, ValueError):
                continue
            if (type(event_id) is int and same_tick and same_importance
                    and str(event.get("kind")) == str(source["kind"])
                    and event.get("payload") == source_payload):
                source_candidates.append(int(event_id))
        if (source_event_id not in source_candidates
                or len(source_candidates) != len(set(source_candidates))):
            return None

        local_candidates = []
        for event in events:
            local = self.store.query_one(
                "SELECT tick,kind,payload_json,importance FROM events WHERE id=?",
                (int(event["id"]),))
            if (local is not None
                    and int(local["tick"]) == int(source["tick"])
                    and str(local["kind"]) == str(source["kind"])
                    and public_event_payload(
                        local["kind"], load_json(local["payload_json"], {}) or {}
                    ) == source_payload
                    and float(local["importance"]) == float(source["importance"])):
                local_candidates.append(int(event["id"]))
        if (len(source_candidates) != len(local_candidates)
                or len(local_candidates) != len(set(local_candidates))):
            replay_reference_error(
                "logical occurrence cardinality mismatch "
                f"(source={len(source_candidates)}, local={len(local_candidates)})")
        occurrence = source_candidates.index(source_event_id)
        if occurrence >= len(local_candidates):
            replay_reference_error(
                f"logical occurrence ordinal {occurrence} is unavailable locally")
        return local_candidates[occurrence]

    def _ground_article(self, outlet: dict, article: Optional[dict],
                        events: list[dict], *,
                        directive: Optional[str] = None) -> Optional[dict]:
        """Fail closed to a deterministic brief when source provenance is bad."""
        if not events:
            return None
        art = dict(article) if isinstance(article, dict) else {}
        headline = art.get("headline")
        body = art.get("body", "")
        raw_tags = art.get("slant_tags")
        raw_tone = art.get("tone", 0.0)
        contract_valid = (
            isinstance(headline, str) and bool(headline.strip())
            and isinstance(body, str)
            and isinstance(raw_tags, list)
            and all(isinstance(tag, str) for tag in raw_tags)
            and type(raw_tone) in {int, float}
            and math.isfinite(float(raw_tone))
        )
        raw_sources = art.get("source_event_ids", [])
        all_sources_valid = isinstance(raw_sources, list) and bool(raw_sources)
        if not isinstance(raw_sources, list):
            raw_sources = []
        source_ids = []
        for value in raw_sources:
            # Provider citations are a typed protocol.  Coercing strings or
            # booleans would make malformed/dangling references look valid.
            if type(value) is not int:
                all_sources_valid = False
                continue
            local_event_id = self._logical_source_event_id(value, events)
            if local_event_id is None:
                all_sources_valid = False
            elif local_event_id not in source_ids:
                source_ids.append(local_event_id)

        # An editor response without a valid local source is not publishable.
        # A compact engine-written brief preserves the daily promise without
        # manufacturing facts or hiding the provider contract failure.
        if not contract_valid or not source_ids or not all_sources_valid:
            event = events[0]
            kind = str(event.get("kind", "event"))
            readable = kind.replace("_", " ")
            art = {
                "headline": f"{outlet['name']} daily brief: {readable}",
                "body": (
                    f"The event spine recorded {readable} today. "
                    "This brief is grounded in today's recorded public event."),
                "tone": 0.0,
                "slant_tags": [outlet.get("slant", "neutral"), "daily-brief"],
                "source_event_ids": [int(event["id"])],
            }
        else:
            art["headline"] = sanitize_provider_text(headline).strip()
            art["body"] = sanitize_provider_text(body).strip()
            art["source_event_ids"] = source_ids
            art["slant_tags"] = [
                sanitize_provider_text(tag).strip()[:80]
                for tag in raw_tags if sanitize_provider_text(tag).strip()
            ] or [outlet.get("slant", "neutral")]
            art["tone"] = max(-1.0, min(1.0, float(raw_tone)))
            if directive:
                art["tone"] = max(-1.0, art["tone"] - 0.3)
                art["slant_tags"].append("directed")
        return art

    def _salient_events(self, tick: int) -> list[dict]:
        kinds = tuple(sorted(PUBLIC_REPORTABLE_EVENT_KINDS - {"quiet_day"}))
        placeholders = ",".join("?" for _ in kinds)
        rows = self.store.query(
            f"SELECT * FROM events WHERE tick=? AND importance>=1.5 "
            f"AND kind IN ({placeholders}) ORDER BY importance DESC, id LIMIT 12",
            (tick, *kinds))
        out = []
        for r in rows:
            out.append({"id": int(r["id"]), "tick": int(r["tick"]), "kind": r["kind"],
                        "payload": public_event_payload(
                            r["kind"], load_json(r["payload_json"], {}) or {}),
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
        if self.e.engine_semantics_version >= 7:
            context["engine_semantics_version"] = self.e.engine_semantics_version
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
        if self.e.engine_semantics_version >= 7:
            context["engine_semantics_version"] = self.e.engine_semantics_version
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
        resp = await self.gw.complete(
            req,
            parsed_transform=lambda parsed: self._ground_article(
                outlet, parsed if isinstance(parsed, dict) else {}, events,
                directive=directive),
        )
        art = resp.parsed if isinstance(resp.parsed, dict) else {}
        return art


class Conversations:
    def __init__(self, economy: Economy, gateway: Gateway, config: dict):
        self.e = economy
        self.store = economy.store
        self.gw = gateway
        self.config = config
        self.mem = Memory(self.store)
        self.turns = int(config.get("conversations", {}).get("turns", 3))
        self.coverage_first = bool(
            config.get("conversations", {}).get("coverage_first", False))
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
        civic_presence = (
            int(self.config.get("engine_semantics_version", 1)) >= 12
            and bool(self.config.get("city", {}).get("enabled", False))
        )
        if civic_presence:
            ties = self.store.query(
                "SELECT t.agent_a,t.agent_b,t.weight,"
                "x.retired AS a_retired,y.retired AS b_retired "
                "FROM social_ties t "
                "JOIN agents x ON x.id=t.agent_a "
                "JOIN agents y ON y.id=t.agent_b "
                "JOIN effective_presence px "
                "ON px.agent_id=t.agent_a AND px.tick=? AND px.slot='evening' "
                "JOIN effective_presence py "
                "ON py.agent_id=t.agent_b AND py.tick=px.tick "
                "AND py.slot=px.slot AND py.place_id=px.place_id "
                "WHERE x.alive=1 AND y.alive=1",
                (int(tick),),
            )
        else:
            ties = self.store.query(
                "SELECT t.agent_a, t.agent_b, t.weight,"
                "x.retired AS a_retired,y.retired AS b_retired "
                "FROM social_ties t "
                "JOIN agents x ON x.id=t.agent_a JOIN agents y ON y.id=t.agent_b "
                "WHERE x.alive=1 AND y.alive=1")
        if not ties:
            return []
        # Weight by tie strength + event salience (agents touched by big events talk).
        salient = {int(r["agent_id"]) for r in self.store.query(
            "SELECT agent_id FROM memories WHERE tick>=? AND importance>=2.5", (tick - 1,))}
        weighted = []
        for t in ties:
            w = float(t["weight"])
            if int(t["agent_a"]) in salient or int(t["agent_b"]) in salient:
                w *= 3.0
            if (int(self.config.get("engine_semantics_version", 1)) >= 7
                    and (bool(t["a_retired"]) or bool(t["b_retired"]))):
                w *= max(1.0, float(self.config.get("conversations", {}).get(
                    "retiree_pair_weight", 1.75)))
            weighted.append((w, int(t["agent_a"]), int(t["agent_b"])))
        participation: dict[int, int] = {}
        if self.coverage_first:
            for row in self.store.query(
                    "SELECT participant_ids FROM conversations ORDER BY id"):
                for agent_id in load_json(row["participant_ids"], []):
                    aid = int(agent_id)
                    participation[aid] = participation.get(aid, 0) + 1
        # Deterministic weighted sample without replacement via engine PRNG.
        chosen: list[tuple[int, int]] = []
        pool = weighted[:]
        used: set[int] = set()
        while pool and len(chosen) < k:
            # Without coverage-first pairing the draw stays over the whole
            # remaining pool, so stored runs keep their original PRNG stream.
            candidates = pool
            if self.coverage_first:
                candidates = [
                    item for item in pool
                    if item[1] not in used and item[2] not in used
                ]
                if not candidates:
                    break
                least_covered = min(
                    (
                        min(participation.get(a, 0), participation.get(b, 0)),
                        max(participation.get(a, 0), participation.get(b, 0)),
                    )
                    for _, a, b in candidates
                )
                candidates = [
                    item for item in candidates
                    if (
                        min(
                            participation.get(item[1], 0),
                            participation.get(item[2], 0),
                        ),
                        max(
                            participation.get(item[1], 0),
                            participation.get(item[2], 0),
                        ),
                    ) == least_covered
                ]
            total = sum(w for w, _, _ in candidates)
            r = self.e.prng.random() * total
            acc = 0.0
            pick = candidates[-1]
            for item in candidates:
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
            if self.coverage_first:
                participation[a] = participation.get(a, 0) + 1
                participation[b] = participation.get(b, 0) + 1
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
                "SELECT name, occupation, age, health, kind, population_tier "
                "FROM agents WHERE id=?", (aid,)))
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
            if (int(self.config.get("engine_semantics_version", 1)) >= 5
                    and profiles[speaker].get("population_tier") != "core"):
                # Peripheral dialogue is generated directly by the bounded,
                # deterministic policy. Only the 100-agent core may create a
                # model-call record in living-world runs.
                env = conversation_turn(context)
            else:
                resp = await self.gw.complete(req, schema_hint=schema)
                env = resp.parsed if isinstance(resp.parsed, dict) else {}
            text = str(env.get("text", "")).strip()[:300]
            avoid_texts = recent_utterances + conversation_so_far
            if not text:
                text = self._unique_fallback_line(
                    tick=tick,
                    speaker=speaker,
                    partner_name=str(names[listener]),
                    avoid_texts=avoid_texts,
                )
                env = {"text": text, "rumor_bank": None}
            repeats_question = (
                "?" in text and bool(conversation_so_far)
                and "?" in conversation_so_far[-1]
            )
            if (repeats_question or self._has_ungrounded_detail(text)
                    or self._previously_said(text, avoid_texts)):
                fallback_context = dict(context)
                fallback_context["avoid_texts"] = list(avoid_texts)
                rejected_candidates: list[str] = []
                for attempt in range(1, 10):
                    fallback_context["rng_seed"] = (
                        int(context["rng_seed"]) + 104729 * attempt)
                    fallback = conversation_turn(fallback_context)
                    candidate = str(fallback.get("text", "")).strip()[:300]
                    if not self._previously_said(candidate, avoid_texts):
                        text = candidate
                        env = fallback
                        break
                    rejected_candidates.append(candidate)
                    fallback_context["avoid_texts"].append(candidate)
                else:
                    text = self._unique_fallback_line(
                        tick=tick,
                        speaker=speaker,
                        partner_name=str(names[listener]),
                        avoid_texts=avoid_texts + rejected_candidates,
                    )
                    env = {"text": text, "rumor_bank": None}
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

    def _too_similar(self, text: str, prior_lines: list[str]) -> bool:
        key = self._line_key(text)
        if not key:
            return False
        conversation_config = self.config.get("conversations", {})
        token_threshold = float(conversation_config.get(
            "similarity_jaccard_threshold", 0.82))
        shingle_threshold = float(conversation_config.get(
            "similarity_shingle_threshold", 0.80))
        tokens = key.split()
        token_set = set(tokens)
        shingles = set(zip(tokens, tokens[1:], tokens[2:])) if len(tokens) >= 3 else set()
        for prior in prior_lines:
            prior_key = self._line_key(prior)
            if key == prior_key:
                return True
            prior_tokens = prior_key.split()
            prior_set = set(prior_tokens)
            if token_set and prior_set:
                intersection = len(token_set & prior_set)
                union = len(token_set | prior_set)
                if union and intersection / union >= token_threshold:
                    return True
            if shingles and len(prior_tokens) >= 3:
                prior_shingles = set(zip(
                    prior_tokens, prior_tokens[1:], prior_tokens[2:]))
                overlap = len(shingles & prior_shingles)
                smaller = min(len(shingles), len(prior_shingles))
                if smaller and overlap / smaller >= shingle_threshold:
                    return True
        return False

    def _unique_fallback_line(
            self, *, tick: int, speaker: int, partner_name: str,
            avoid_texts: list[str]) -> str:
        """Return a grounded line outside the bounded scripted phrase bank."""
        openings = (
            "one signal worth watching is",
            "the clearest unresolved question is",
            "a cautious reading should focus on",
            "the next useful comparison is",
            "the practical concern may be",
            "the strongest uncertainty remains",
            "a measured response would track",
            "the part that still needs evidence is",
            "the immediate test could be",
            "the broader issue may be",
        )
        effects = (
            "how household budgets respond",
            "whether hiring plans change",
            "whether prices move before wages",
            "how confidence affects spending",
            "whether smaller firms adjust output",
            "how credit conditions react",
            "whether job security weakens",
            "how demand changes across firms",
            "whether the headline persists",
            "how market concentration develops",
        )
        endings = (
            "before drawing a firm conclusion.",
            "as the next figures arrive.",
            "without assuming the headline tells the whole story.",
            "while the evidence is still limited.",
            "before anyone treats the shift as permanent.",
            "because the current picture remains incomplete.",
        )
        total = len(openings) * len(effects) * len(endings)
        start = (tick * 1009 + speaker * 13) % total
        for offset in range(total):
            index = (start + offset) % total
            opening_index, remainder = divmod(
                index, len(effects) * len(endings))
            effect_index, ending_index = divmod(remainder, len(endings))
            candidate = (
                f"{partner_name}, {openings[opening_index]} "
                f"{effects[effect_index]} {endings[ending_index]}"
            )[:300]
            if (not self._previously_said(candidate, avoid_texts)
                    and not self._has_ungrounded_detail(candidate)):
                return candidate
        return (
            f"{partner_name}, day {tick} still leaves jobs, prices, credit, "
            f"and confidence open to different readings."
        )[:300]

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
