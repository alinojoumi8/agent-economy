# Security policy

## Supported surface

The current v1 application is a local, single-operator research observatory. It
has no authentication, authorization, tenant isolation, CSRF protection, or
internet-facing deployment hardening. Bind it to `127.0.0.1` and do not expose
the FastAPI or Vite servers directly to an untrusted network.

## Secrets and sensitive artifacts

- Put provider credentials only in the ignored `.env` file or process
  environment.
- Never add keys to YAML profiles, reports, screenshots, issues, or pull
  requests.
- Treat run databases as potentially sensitive: they can contain prompts,
  model responses, personas, memories, conversations, and decision evidence.
- Operational logging redacts credential-shaped fields, but review artifacts
  before sharing them outside the project.
- Revoke a provider key immediately if it is exposed and remove it from Git
  history rather than only deleting it in a later commit.

## Reporting a vulnerability

Report security issues privately to the repository owner through GitHub's
private vulnerability reporting if enabled, or another private channel. Include
reproduction steps, affected commit/profile, impact, and a suggested mitigation.
Do not publish credentials or sensitive run contents in a public issue.

Hosted multi-user mode is deferred work. Before enabling it, add an explicit
threat model, authentication and authorization, tenant/data isolation, request
limits, audit retention policy, encrypted secret storage, and deployment
hardening.
