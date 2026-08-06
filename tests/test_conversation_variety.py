import asyncio
import json
from types import SimpleNamespace

from agents.policies import conversation_turn
from engine.store import Store
from world.loop import World
from world.newsroom import Conversations


def _world(tmp_path, conversation_config: dict | None = None) -> World:
    config = {
        "seed": 42,
        "population": {"size": 24},
        "banks": {"count": 2},
        "firms": {"count": 5, "listed": 2},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0,
                   "conversation_pairs": 8},
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"},
                "routes": {}},
        "checkpoint_every": 0,
        "outlets": [
            {"id": 1, "name": "A", "slant": "pro-market-sensational"},
            {"id": 2, "name": "B", "slant": "cautious-pro-labor"},
        ],
    }
    if conversation_config is not None:
        config["conversations"] = conversation_config
    store = Store(str(tmp_path / "conversation-variety.db"))
    store.init_run_meta("conversation-variety", config["seed"], config)
    world = World(store, config)
    world.initialize()
    return world


def test_full_horizon_similarity_window_retains_all_sixty_days(tmp_path):
    world = _world(tmp_path, {
        "turns": 2,
        "recent_utterance_limit": 360,
        "similarity_jaccard_threshold": 0.65,
        "similarity_shingle_threshold": 0.65,
    })
    for index in range(120):
        world.conversations._remember_line(
            index % 25 + 1, "market conditions", f"unique line {index}")

    assert world.conversations._recent_global.maxlen == 120
    assert len(world.conversations._recent_global) == 120
    assert world.conversations._recent_global[0] == "unique line 0"


def test_coverage_first_pairs_give_every_eligible_agent_a_turn(tmp_path):
    world = _world(tmp_path)
    conversations = world.conversations
    conversations.turns = 2
    conversations.coverage_first = True
    eligible = {
        int(row["agent_id"])
        for row in world.store.query(
            "SELECT agent_a AS agent_id FROM social_ties "
            "UNION SELECT agent_b AS agent_id FROM social_ties")
    }

    covered: set[int] = set()
    for tick in range(1, len(eligible) * 2 + 1):
        pairs = conversations._sample_pairs(tick, 1)
        assert pairs
        a_id, b_id = pairs[0]
        asyncio.run(conversations._converse(tick, a_id, b_id))
        covered.update((a_id, b_id))
        if covered == eligible:
            break

    assert covered == eligible
    for row in world.store.query(
            "SELECT id,participant_ids FROM conversations ORDER BY id"):
        participants = {int(value) for value in json.loads(
            row["participant_ids"])}
        authors = {
            int(message["agent_id"])
            for message in world.store.query(
                "SELECT agent_id FROM messages WHERE conv_id=? ORDER BY seq",
                (int(row["id"]),),
            )
        }
        assert authors == participants


def test_scripted_conversation_avoids_recent_lines_and_answers_questions():
    context = {
        "tick": 4,
        "partner_name": "Mara",
        "shared_topic": "Firms expand hiring",
        "rng_seed": 99,
        "conversation_so_far": [],
        "avoid_texts": [],
    }
    first = conversation_turn(context)["text"]
    context["avoid_texts"] = [first]
    second = conversation_turn(context)["text"]
    assert second != first

    context["conversation_so_far"] = ["Do you think hiring will last?"]
    response = conversation_turn(context)["text"]
    assert "?" not in response

    context["speaker_rumor_bank"] = 2
    rumor_response = conversation_turn(context)["text"]
    assert "?" not in rumor_response


def test_grounding_guard_rejects_live_provider_backstories():
    unsupported = [
        "I know a few people over at Firm 5, and they told me about the layoffs.",
        "I sat down with my receipts last week and prices had doubled from years ago.",
        "The school has been hinting that my contract may not be safe next term.",
        "My suppliers and clients are already calling their attorneys about arbitration.",
        "I saw the move on LinkedIn before the paperwork was final.",
        "Patients are rationing medicine because the grocery bill swallowed their budget.",
        "The school has been trimming shifts and the local branch feels it first.",
    ]
    grounded = [
        "These layoffs could make households more cautious about spending.",
        "Do you think this price gap could weaken confidence?",
        "The headline may not tell the whole story.",
    ]
    assert all(Conversations._has_ungrounded_detail(line) for line in unsupported)
    assert not any(Conversations._has_ungrounded_detail(line) for line in grounded)


def test_configured_similarity_guard_rejects_repeated_stock_reply(tmp_path):
    world = _world(tmp_path)
    world.conversations.config["conversations"] = {
        "similarity_jaccard_threshold": 0.65,
        "similarity_shingle_threshold": 0.65,
    }
    prior = [
        "That is fair, Reporter The Ledger; we may need tomorrow's "
        "numbers to understand the effects."
    ]
    repeated = (
        "That is fair, Secretary Lin; we may need tomorrow's numbers "
        "to understand the effects."
    )

    assert world.conversations._previously_said(repeated, prior)


def test_conversation_replaces_ungrounded_provider_output(tmp_path):
    world = _world(tmp_path)
    agent_ids = [int(row["id"]) for row in world.store.query(
        "SELECT id FROM agents WHERE alive=1 ORDER BY id LIMIT 2")]
    raw_line = "I saw it on LinkedIn after my clients called their attorneys last week."

    async def ungrounded_completion(request, **kwargs):
        return SimpleNamespace(parsed={"text": raw_line, "rumor_bank": None})

    world.conversations.gw.complete = ungrounded_completion
    asyncio.run(world.conversations._converse(1, agent_ids[0], agent_ids[1]))

    lines = [str(row["text"]) for row in world.store.query(
        "SELECT text FROM messages ORDER BY seq")]
    assert len(lines) == world.conversations.turns
    assert raw_line not in lines
    assert len(set(lines)) == len(lines)


def test_conversation_rng_and_prior_lines_are_not_numeric_grounding_sources(tmp_path):
    world = _world(tmp_path)
    world.config["beliefs"] = {"model_grounding_from_tick": 1}
    world.conversations.config = world.config
    agent_ids = [int(row["id"]) for row in world.store.query(
        "SELECT id FROM agents WHERE alive=1 ORDER BY id LIMIT 2")]
    raw_lines = []

    async def seeded_completion(request, **kwargs):
        raw = f"Conditions may shift around {request.context['rng_seed']}."
        raw_lines.append(raw)
        return SimpleNamespace(parsed={"text": raw, "rumor_bank": None})

    world.conversations.gw.complete = seeded_completion
    asyncio.run(world.conversations._converse(1, agent_ids[0], agent_ids[1]))

    stored = [str(row["text"]) for row in world.store.query(
        "SELECT text FROM messages ORDER BY seq")]
    assert raw_lines
    assert stored
    assert not set(raw_lines) & set(stored)
    world.close()


def test_conversation_persists_nonempty_sanitized_provider_text(
        tmp_path, monkeypatch):
    world = _world(tmp_path)
    world.config["beliefs"] = {"model_grounding_from_tick": 1}
    world.conversations.config = world.config
    world.conversations.turns = 1
    agent_ids = [int(row["id"]) for row in world.store.query(
        "SELECT id FROM agents WHERE alive=1 ORDER BY id LIMIT 2")]
    raw_line = "Provider text with an unsupported 987654321% claim."
    sanitized_line = "Conditions may change after the unsupported claim is removed."

    async def completion(request, **kwargs):
        return SimpleNamespace(parsed={"text": raw_line, "rumor_bank": None})

    monkeypatch.setattr(
        "world.newsroom.sanitize_model_numeric_narrative",
        lambda *args, **kwargs: sanitized_line,
    )
    world.conversations.gw.complete = completion

    asyncio.run(world.conversations._converse(
        1, agent_ids[0], agent_ids[1]))

    assert world.store.scalar(
        "SELECT text FROM messages ORDER BY seq LIMIT 1") == sanitized_line
    world.close()


def test_conversation_uses_the_configured_output_budget(tmp_path):
    world = _world(tmp_path)
    world.conversations.config["llm"]["conversation_max_tokens"] = 800
    agent_ids = [int(row["id"]) for row in world.store.query(
        "SELECT id FROM agents WHERE alive=1 ORDER BY id LIMIT 2")]
    requested_budgets = []

    async def completion(request, **kwargs):
        requested_budgets.append(request.max_tokens)
        return SimpleNamespace(parsed={
            "text": f"A grounded response for turn {len(requested_budgets)}.",
            "rumor_bank": None,
        })

    world.conversations.gw.complete = completion
    asyncio.run(world.conversations._converse(1, agent_ids[0], agent_ids[1]))

    assert requested_budgets == [800, 800, 800]


def test_newsroom_uses_configured_reporter_and_editor_output_budgets(tmp_path):
    world = _world(tmp_path)
    world.newsroom.config["llm"].update({
        "reporter_max_tokens": 1600,
        "newsroom_max_tokens": 1200,
    })
    requested_budgets = []

    async def completion(request, **kwargs):
        requested_budgets.append((request.purpose, request.max_tokens))
        if request.purpose == "reporter":
            return SimpleNamespace(parsed={"stories": []})
        return SimpleNamespace(parsed={
            "headline": "Measured production",
            "body": "Output changed within the supplied evidence.",
            "tone": 0.0,
            "slant_tags": [],
            "source_event_ids": [1],
        })

    world.newsroom.gw.complete = completion

    async def exercise_newsroom():
        outlet = {"id": 1, "name": "A", "slant": "cautious"}
        events = [{"id": 1, "kind": "production", "payload": {"quantity": 4}}]
        drafts = await world.newsroom._report_stories(1, outlet, events)
        await world.newsroom._write_story(1, outlet, events, None, drafts)

    asyncio.run(exercise_newsroom())

    assert requested_budgets == [("reporter", 1600), ("newsroom", 1200)]


def test_live_output_budget_activation_preserves_historical_tick_contracts(tmp_path):
    world = _world(tmp_path)
    world.newsroom.config["llm"].update({
        "reporter_max_tokens": 1600,
        "newsroom_max_tokens": 1200,
        "output_budget_activation_tick": 2,
    })
    requested_budgets = []

    async def completion(request, **kwargs):
        requested_budgets.append((request.tick, request.purpose, request.max_tokens))
        if request.purpose == "reporter":
            return SimpleNamespace(parsed={"stories": []})
        return SimpleNamespace(parsed={
            "headline": "Measured production",
            "body": "Output changed within the supplied evidence.",
            "tone": 0.0,
            "slant_tags": [],
            "source_event_ids": [1],
        })

    world.newsroom.gw.complete = completion

    async def exercise_newsroom():
        outlet = {"id": 1, "name": "A", "slant": "cautious"}
        events = [{"id": 1, "kind": "production", "payload": {"quantity": 4}}]
        for tick in (1, 2):
            drafts = await world.newsroom._report_stories(tick, outlet, events)
            await world.newsroom._write_story(tick, outlet, events, None, drafts)

    asyncio.run(exercise_newsroom())

    assert requested_budgets == [
        (1, "reporter", 500),
        (1, "newsroom", 400),
        (2, "reporter", 1600),
        (2, "newsroom", 1200),
    ]


def test_conversation_replaces_missing_provider_text(tmp_path):
    world = _world(tmp_path)
    world.conversations.turns = 2
    agent_ids = [int(row["id"]) for row in world.store.query(
        "SELECT id FROM agents WHERE alive=1 ORDER BY id LIMIT 2")]

    async def missing_text_completion(request, **kwargs):
        return SimpleNamespace(parsed={
            "actions": [{"type": "do_nothing"}],
            "reasoning": "unparseable output; no-op",
        })

    world.conversations.gw.complete = missing_text_completion
    asyncio.run(world.conversations._converse(
        1, agent_ids[0], agent_ids[1]))

    lines = list(world.store.query(
        "SELECT agent_id,text FROM messages ORDER BY seq"))
    assert len(lines) == 2
    assert {int(row["agent_id"]) for row in lines} == set(agent_ids)
    assert all(str(row["text"]).strip() for row in lines)


def test_fallback_exhaustion_uses_a_genuinely_unique_line(
        tmp_path, monkeypatch):
    world = _world(tmp_path)
    agent_ids = [int(row["id"]) for row in world.store.query(
        "SELECT id FROM agents WHERE alive=1 ORDER BY id LIMIT 2")]
    repeated = "The part I keep coming back to is who bears the cost first."
    world.conversations._remember_line(
        agent_ids[0], "market conditions", repeated)

    async def ungrounded_completion(request, **kwargs):
        return SimpleNamespace(parsed={
            "text": "I saw it on LinkedIn after my clients called last week.",
            "rumor_bank": None,
        })

    monkeypatch.setattr(
        "world.newsroom.conversation_turn",
        lambda context: {"text": repeated, "rumor_bank": None},
    )
    world.conversations.gw.complete = ungrounded_completion
    asyncio.run(world.conversations._converse(
        1, agent_ids[0], agent_ids[1]))

    prior = [repeated]
    for row in world.store.query(
            "SELECT text FROM messages ORDER BY seq"):
        text = str(row["text"])
        assert not world.conversations._too_similar(text, prior)
        prior.append(text)


def test_shared_topics_rotate_across_conversation_pairs(tmp_path):
    world = _world(tmp_path)
    for index, headline in enumerate(("Jobs rise", "Prices ease", "Bank expands", "Sales climb"), 1):
        world.store.insert(
            "news_articles", tick=1, outlet_id=index, headline=headline,
            body="body", source_event_ids="[]", slant_tags="[]", tone=0.0)

    topics = [world.conversations._shared_topic(1, topic_slot=slot) for slot in range(8)]
    assert topics[:4] == ["Sales climb", "Bank expands", "Prices ease", "Jobs rise"]
    assert len(set(topics)) == 8
    assert "household budgets and the price of essentials" in topics


def test_shared_topic_uses_the_publicly_grounded_article_projection(tmp_path):
    world = _world(tmp_path)
    try:
        world.config["beliefs"] = {"model_grounding_from_tick": 1}
        world.conversations.config["beliefs"] = {
            "model_grounding_from_tick": 1}
        event_id = world.store.log_event(
            1, "production", {"firm_id": 1, "units": 4},
            phase="NIGHT_CLOSE", importance=1.0)
        world.store.insert(
            "news_articles", tick=1, outlet_id=1, outlet_name="A",
            headline="Output jumped 987654321%",
            body="The unsupported increase was 987654321%.",
            source_event_ids=json.dumps([event_id]), slant_tags="[]", tone=0.0)
        world.store.commit()

        topic = world.conversations._shared_topic(1)

        assert "987654321" not in topic
        assert topic == "A archived brief: production"
    finally:
        world.close()


def test_theme_rotation_advances_by_daily_pair_count(tmp_path):
    world = _world(tmp_path)
    world.conversations.config["budget"]["conversation_pairs"] = 4
    day_one = {
        world.conversations._shared_topic(1, topic_slot=slot) for slot in range(4)
    }
    day_two = {
        world.conversations._shared_topic(2, topic_slot=slot) for slot in range(4)
    }
    assert len(day_one) == 4
    assert len(day_two) == 4
    assert len(day_one & day_two) == 1


def test_conversation_day_has_varied_topics_and_no_duplicate_turns(tmp_path):
    world = _world(tmp_path)
    for outlet_id, headline in ((1, "Hiring rises"), (2, "Prices cool")):
        world.store.insert(
            "news_articles", tick=1, outlet_id=outlet_id, headline=headline,
            body="body", source_event_ids="[]", slant_tags="[]", tone=0.0)
    asyncio.run(world.step())

    topic_count = world.store.scalar(
        "SELECT COUNT(DISTINCT topic) FROM conversations WHERE tick=1", default=0)
    total_messages = world.store.scalar(
        "SELECT COUNT(*) FROM messages WHERE tick=1", default=0)
    distinct_messages = world.store.scalar(
        "SELECT COUNT(DISTINCT lower(trim(text))) FROM messages WHERE tick=1", default=0)

    assert topic_count >= 6
    assert total_messages > 0
    assert distinct_messages == total_messages
    request_json = world.store.scalar(
        "SELECT request_json FROM llm_calls WHERE purpose='conversation' ORDER BY id LIMIT 1",
        default="")
    assert "do not invent laws" in str(request_json).lower()
    for row in world.store.query(
            "SELECT conv_id, SUM(CASE WHEN instr(text, '?') > 0 THEN 1 ELSE 0 END) AS questions "
            "FROM messages WHERE tick=1 GROUP BY conv_id"):
        assert int(row["questions"]) <= 2
