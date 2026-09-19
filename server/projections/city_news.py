"""Public, numerically grounded newsroom stories for the selected City day."""
from engine.store import load_json
from world.newsroom import _public_article_projection


def build_city_news(store, *, as_of_tick: int, limit: int = 30, before_id: int | None = None) -> dict:
    rows = store.query(
        "SELECT * FROM news_articles WHERE tick=? AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?",
        (as_of_tick, before_id, before_id, limit + 1))
    config = load_json(store.get_meta()["config_json"], {}) or {}
    items = []
    for raw in rows[:limit]:
        article = dict(raw)
        raw_ids = load_json(article.get("source_event_ids"), []) or []
        article["source_event_ids"] = [eid for eid in raw_ids if type(eid) is int and store.query_one(
            "SELECT id FROM events WHERE id=? AND tick<=?", (eid, as_of_tick))]
        public = _public_article_projection(store, config, article, enforcement_tick=as_of_tick)
        items.append({key: public.get(key) for key in (
            "id", "tick", "outlet_name", "headline", "body", "source_event_ids", "numeric_claims_redacted")})
    return {"tick": as_of_tick, "items": items, "source": "public_newsroom",
            "next_before_id": items[-1]["id"] if len(rows) > limit and items else None}
