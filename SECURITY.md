# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a security vulnerability. Report it privately instead:

- **Email:** martin_otis@uqac.ca
- Or use GitHub's [private vulnerability reporting](https://github.com/LARi-UQAC/ResearchTools/security/advisories/new) if enabled for this repository.

Include a description of the vulnerability, the affected component (skill / agent / command /
hook), and reproduction steps where possible.

## Scope and threat model

This repository runs locally on a researcher's machine: no authentication, TLS, or exposed
service by default. The one exception is the optional `deploy/form-service/` HTTP API — see
its own notes in [.claude/rules/security.md](.claude/rules/security.md). Realistic threats are
a malicious input file, a malformed request corrupting local state or audit logs, an untrusted
dependency, or a leaked secret — not enterprise compliance scenarios (SOC 2, HIPAA, PCI DSS,
GDPR, ISO 27001 do not apply here).

## Supported versions

| Version | Supported |
|---|---|
| `main` / latest tag | ✅ |

There is no long-term support branch; fixes land on `main`.

## Dependency auditing

Every dependency change goes through `pip-audit`. Full workflow, CVSS grading, and hashed-
lockfile verification: [.claude/rules/security.md](.claude/rules/security.md).

## Active security hooks

`betterleaks-hook.py` (blocks writes containing a detected secret), `pip-audit-hook.py` (warns
on a CVE in a modified `requirements.txt`), and `prompt-injection-defender.py` (warns on
suspicious tool output) run automatically in every Claude Code session working in this
repository. They protect the Claude Code workflow, not an external contributor using plain git.
