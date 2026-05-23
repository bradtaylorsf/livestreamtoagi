# Security Policy

Livestream to AGI is pre-alpha research software. Please do not run it as a
public autonomous service without reviewing the safety gates, secrets, cost
controls, and Minecraft/legal posture.

## Reporting A Vulnerability

Please report vulnerabilities privately to the repository owner before opening
a public issue. Include:

- Affected component or file path.
- Reproduction steps.
- Expected impact.
- Whether credentials, external communications, LLM spend, sandbox escape, or
  public broadcast output are involved.

If you are unsure whether something is security-sensitive, treat it as private.

## Supported Versions

Only `main` is currently supported. There are no stable releases yet.

## High-Risk Areas

- Secrets and tokens in `.env`, GitHub Actions, Minecraft bridge config, and
  local run scripts.
- LLM routing and cost governance.
- Management content filtering before TTS or public broadcast.
- Admin routes, public simulation submission, auth cookies/JWTs, and magic-link
  email flow.
- Sandboxed code execution and subprocess launch paths.
- Minecraft bridge authentication and query-token fallbacks.
- YouTube/social/email publishing and any other external communication path.

## Baseline Checks

```bash
git status --short
git ls-files | grep -E '(^\\.env$|\\.pem$|\\.key$|\\.p12$|\\.log$|\\.mp4$)' || true
.venv/bin/ruff check core/ tools/
make test-backend
npm --prefix frontend audit --audit-level=high
npm --prefix website audit --audit-level=high
```

CI also runs Bandit, pip-audit, npm audit, backend tests, frontend tests,
website tests, memory regression tests, and render pipeline tests.
