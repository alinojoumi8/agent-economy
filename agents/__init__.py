"""Agent runtime: personas, memory, scheduler, prompt assembly, decision loop.

Agents *propose* structured actions; the engine disposes. This package assembles
each agent's context (persona + state + beliefs + retrieved memories + today's
news), calls the gateway, and hands the returned action list to the executor.
"""
