# Draft Reddit — r/selfhosted

> Titre : I built an autonomous AI agent that runs 24/7 on a cheap $7/mo VM — no Docker, no Redis, no Postgres, just Python + SQLite

---

**Santana** is an autonomous AI agent I've been running for weeks on a GCP e2-micro (2 vCPUs, 2GB RAM, ~$7/mo). It has persistent memory (remembers conversations across sessions), web search, GitHub integration, sandboxed code execution, and talks to me on Telegram.

The key design constraint: **zero infrastructure**. No Docker, no Redis, no PostgreSQL. The whole thing is a single Python 3.11+ process using SQLite in WAL mode. It costs ~$8-10/mo in LLM inference (DeepSeek V4 Flash with 95% cache hit rate).

## What it does for me

- Answers questions with web search context
- Manages GitHub repos (create/edit files, check PRs)
- Remembers what we discussed days ago (3-layer memory: session buffer → summaries → SQLite vector embeddings)
- Runs code in a sandboxed subprocess
- Monitors its own spending and throttles itself when over budget
- Available on Telegram and REST API

## The frugal stack

| Component | What I use |
|-----------|-----------|
| VM | GCP e2-micro (~$7/mo) |
| LLM | DeepSeek V4 Flash (~$8-10/mo at 1M tokens/day) |
| Embeddings | all-MiniLM-L6-v2 (80MB, runs on CPU, no GPU) |
| Database | SQLite (WAL mode, aiosqlite) |
| Fallback LLMs | OpenRouter, Nous Portal |
| Web search | Serper API (free tier) |

## Why not use existing frameworks?

I tried LangChain, AutoGPT, and CrewAI. Every single one wants Docker, Redis, Postgres, or costs $50+/mo in managed inference. For a personal agent that just answers questions and runs tasks, that felt like enterprise overkill.

Santana is opinionated: one Python process, SQLite, and a cheap LLM. That's it.

## Links

- **GitHub**: https://github.com/BadTechResearch/santana
- **Release**: https://github.com/BadTechResearch/santana/releases/tag/v2.0.0
- **Architecture doc**: https://github.com/BadTechResearch/santana/blob/main/docs/ARCHITECTURE.md

Happy to answer questions about the architecture, cost, or trade-offs I made. What do you use for your personal agents?
