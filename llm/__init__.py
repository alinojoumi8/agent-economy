"""LLM gateway: the single chokepoint every model call flows through.

Routing (role → {provider, model}), budget governor with staged degradation,
prompt-prefix caching, structured-output parsing with one retry, concurrency
limits, and full request/response logging for the inspector + exact replay.
"""
