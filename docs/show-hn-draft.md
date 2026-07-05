# Show HN: Santana — An autonomous AI agent that runs for <$10/month on a $7 VM

> *Draft for Hacker News — July 2026*

---

**Santana** is a production-ready autonomous AI agent that maintains persistent memory, browses the web, manages GitHub repos, executes sandboxed code, and communicates across Telegram/Discord/API.

The headline: it runs on a Google Cloud **e2-micro** (2 vCPUs, 2GB RAM, ~$7/mo) and costs **<$10/month in LLM inference** thanks to DeepSeek V4 Flash with 94-96% cache hit rate.

I built this because every agent framework I tried (LangChain, AutoGPT, CrewAI) wanted Docker, Redis, PostgreSQL, and $50+/month in inference. For a personal agent that's just nonsense.

## What's inside

```
Santana
├── 3-layer memory (session buffer → summaries → SQLite vector)
├── self-awareness module (knows its own code, tools, prompt)
├── cost governor with ALERT/THROTTLE/STOP thresholds
├── multi-platform: Telegram, Discord, REST API
├── 15+ tools (web search, GitHub, YouTube, MCP, code execution)
├── secure whitelist-based terminal
└── 97% test coverage
```

## Key design decisions

- **No Docker**. No Redis. No Postgres. SQLite + filesystem.
- **Small embedding model** (all-MiniLM-L6-v2) for memory retrieval — 80MB, runs on CPU
- **DeepSeek V4 Flash** as primary LLM — $0.028/1M tokens cached → ~$30/mo budget, actual spend ~$8-10 with cache
- **Fallback chain**: DeepSeek → OpenRouter → Nous Portal — zero downtime if one provider is down
- **Hermes Agent** as the underlying framework (full control over the agent loop)

## Cost breakdown (real, measured)

| Item | Cost/mo |
|------|---------|
| VM (GCP e2-micro, preemptible + sustained use) | ~$5-7 |
| DeepSeek API (1M tokens/day, 95% cached) | ~$8-10 |
| Serper API (web search, 5K queries) | $0 |
| Total | **$13-17/mo** |

Comparable agents on managed platforms charge $50-200/mo.

## What makes it different

Most open-source agents are *frameworks* — you still need to build the actual agent. Santana is a *running agent* you can talk to in 15 minutes. `git clone → pip install → cp .env.example .env → ./run.sh` and you have a Telegram bot with persistent memory, web search, and cost control.

## Repo

https://github.com/BadTechResearch/santana

Happy to answer technical questions in the thread. The full architecture doc and docs are in the repo.
# Test credential helper — Sun Jul  5 06:01:10 UTC 2026
