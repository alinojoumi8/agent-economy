import asyncio
from types import SimpleNamespace

from agents.policies import conversation_turn
from engine.store import Store
from world.loop import World
from world.newsroom import Conversations


def _world(tmp_path) -> World:
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
    store = Store(str(tmp_path / "conversation-variety.db"))
    store.init_run_meta("conversation-variety", config["seed"], config)
    world = World(store, config)
    world.initialize()
    return world


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
