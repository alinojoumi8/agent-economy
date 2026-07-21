# Hermes

Merge `mcp-config.yaml` into the Hermes configuration, replace the URL and
one-time token, then run `hermes mcp test agent_economy`. Remove tools not
granted to the connection if the selected tier is observer or Commons-only.

Do not commit the filled configuration. Prefer the hosted OAuth flow when the
Hermes deployment can complete browser authorization; the bearer example is
for a scoped headless personal agent token.
