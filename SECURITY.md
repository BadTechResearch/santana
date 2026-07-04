# Security Policy

## Supported Versions

Only the latest commit on the `main` branch is actively supported.  
No backports — update to the latest version for security fixes.

| Version | Supported |
|---------|-----------|
| `main` (HEAD) | ✅ Active |
| Older tags/commits | ❌ Not supported |

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Send an email or a direct Telegram message to the maintainer:

- **Telegram:** [@Serge](https://t.me/Serge) (preferred, fastest response)
- **Response time:** < 48 hours for initial acknowledgment

### What to include

1. Description of the vulnerability
2. Steps to reproduce (proof of concept preferred)
3. Affected component / file(s)
4. Severity estimate (low / medium / high / critical)
5. Any suggested fix (if available)

### Disclosure policy

1. Report received → acknowledgment within 48h
2. Triage & investigation → within 5 business days
3. If confirmed → fix developed, tested, and deployed
4. Public disclosure coordinated with reporter, typically 30 days after fix

---

## Security measures in Santana

### Token protection
- All API keys are read from environment variables (`.env`, never tracked in git)
- `.env` files are in `.gitignore` and excluded from version control
- The `.env.example` contains only placeholder values
- GitHub tokens are fine-grained with minimal scopes

### Code execution sandbox
- `tools/vm_security.py` implements a strict allowlist of ~30 system commands
- Dangerous operators (`;`, `` ` ``, `$()`, `|`, `&&`) are blocked at the parser level
- Shell glob / brace expansion bypasses are specifically blocked
- Git subcommands (checkout, reset, push, clean) are filtered
- Danger patterns: `find -exec`, `rm -rf`, pipe chains are rejected

### Network security
- API server binds to `127.0.0.1` only (not exposed externally)
- Telegram bot runs via polling (no public webhook endpoint)
- All external API calls use HTTPS
- No open ports other than the configured bot platforms

### Cost protection
- `core/cost_governor.py` sets hard budget limits (`ALERT` → `THROTTLE` → `STOP`)
- LLM calls are blocked once the daily budget is exceeded
- Budget is configurable via `DEEPSEEK_COST_LIMIT` (default: $0.01/day)

### Runtime protections
- `agent/securite.py` monitors rate limits per tool
- `agent/soiute.py` ensures tool isolation (tools cannot expose other tools)
- `agent/tracabilite.py` logs all decisions and actions for audit
- Santana runs as a systemd user service with strict resource limits

---

## Security audit history

| Date | Scope | Findings | Status |
|------|-------|----------|--------|
| 2026-06-22 | VM security, allowlist, bypasses, port scan | 3 bypasses (git show, pytest, pip install), 2 .env files with loose permissions (664) | ✅ All fixed |
| 2026-07-04 | Full repo audit, 4 channels (HEAD, history, .gitignore, GitHub profile), clone verify | 0 tokens, 0 personal data, 0 exposed secrets | ✅ Clean |
| 2026-07-04 | Local permissions verification | `~/.hermes/.env` was 664 (fixed → 600), auto-check added to doctor script | ✅ Fixed + automated |

## Dependencies

Dependencies are pinned in `requirements.txt` and `requirements-lock.txt`.  
Review updated dependencies before upgrading, especially:
- `python-telegram-bot` (API changes, new features)
- `deepseek` client (rate limit changes, endpoint changes)
- Any package with native extensions (cryptography, ctranslate2, etc.)

---

## Responsible disclosure

We believe in responsible disclosure. If you've found a vulnerability:

1. Contact us privately first (Telegram: [@Serge](https://t.me/Serge))
2. Allow reasonable time for a fix before public disclosure
3. Do not exploit the vulnerability beyond what's necessary to demonstrate it

We will credit you in this file (unless you prefer to remain anonymous).
