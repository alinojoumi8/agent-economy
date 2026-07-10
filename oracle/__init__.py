"""The Oracle: a read-only live analyst over world state (PRD R6, TECH-SPEC §11).

It answers probability questions with a point estimate + drivers + a machine-
checkable resolution rule and deadline; predictions are logged and auto-resolved,
and Brier scores accumulate. It has NO write access to the world.
"""
