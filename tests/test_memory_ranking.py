from agents.memory import Memory
from engine.store import Store


def test_memory_retrieval_uses_weighted_addition_not_multiplication(tmp_path):
    store = Store(str(tmp_path / "memory-ranking.db"))
    store.init_run_meta("memory-ranking", 17, {})
    memory = Memory(store)

    query_entities = [f"topic-{index}" for index in range(10)]
    memory.observe(
        1,
        40,
        "recent but narrowly relevant",
        importance=1.5,
        entities=[query_entities[0]],
    )
    memory.observe(
        1,
        0,
        "old but important and broadly relevant",
        importance=10.0,
        entities=query_entities,
    )

    # A multiplicative interpretation would rank the old memory first:
    # 0.0625 * 1.0 * 1.0 > 1.0 * 0.15 * 0.1.  The TECH-SPEC's
    # additive formula instead gives the recent memory 0.565 versus 0.53125.
    multiplicative_recent = 1.0 * 0.15 * 0.1
    multiplicative_old = 0.0625 * 1.0 * 1.0
    assert multiplicative_old > multiplicative_recent

    ranked = memory.retrieve(1, tick=40, k=2, query_entities=query_entities)
    assert [row["text"] for row in ranked] == [
        "recent but narrowly relevant",
        "old but important and broadly relevant",
    ]
