# Show HN: Santana — Autonomous AI Agent That Runs for <$10/mo on a $7 VM

> *Final draft — July 2026*

---

Santana is a production-ready autonomous AI agent with persistent memory, web search, GitHub integration, and code execution on Telegram.

The headline number: it runs on a **GCP e2-micro** (2 vCPUs, 2GB RAM, ~$7/mo) and costs **<$10/mo in LLM inference** — ~$17/mo total.

I built this because every agent framework I tried (LangChain, AutoGPT, CrewAI) had the same pattern: Docker, Redis, PostgreSQL, and $50+ in inference for a personal agent. That's absurd for something that should just answer questions and run tasks.

## What makes it different

Most open-source agents are *frameworks* — you get a design doc and 20 dependencies. Santana is a *running agent*.

```
git clone https://github.com/BadTechResearch/santana
cd santana
pip install -r requirements.txt
cp .env.example .env
# edit .env with your API keys
python santana.py
```

15 minutes later you have a Telegram bot that remembers conversations, searches the web, reads GitHub repos, runs sandboxed Python, and monitors its own costs.

## Design decisions

- **No Docker, no Redis, no Postgres** — SQLite (WAL mode) + filesystem. The whole agent is one Python process.
- **Small embedding model** — all-MiniLM-L6-v2 (80MB, runs on CPU). No GPU needed.
- **DeepSeek V4 Flash** as primary LLM — $0.028/1M cached tokens. 94-96% cache hit rate means ~$8-10/mo for 1M tokens/day.
- **Fallback chain**: DeepSeek → OpenRouter → Nous Portal — zero provider lock-in.
- **Cost governor** with ALERT/THROTTLE/STOP thresholds — it tells you when it's spending too much and throttles itself.

## Real cost breakdown (measured on my VM)

| Item | Cost/mo |
|------|---------|
| VM (GCP e2-micro, preemptible + sustained use) | ~$5-7 |
| DeepSeek API (1M tokens/day, 95% cached) | ~$8-10 |
| Serper API (web search, 5K queries) | $0 (free tier) |
| **Total** | **$13-17/mo** |

Comparable hosted agents charge $50-200/mo.

## 3-layer memory

1. **Session buffer** — full conversation context (sliding window)
2. **Summaries** — compressed history for long-term context
3. **SQLite vector store** — embeddings for semantic retrieval (all-MiniLM-L6-v2)

Memory persists across restarts, sessions, and platforms. Talk to it on Telegram, then ask later "what were we working on yesterday?" — it remembers.

## Tools (15+)

Web search (Google + social), GitHub (read/write repos, manage files), sandboxed Python execution, whitelisted terminal, YouTube search, Twitter search, MCP client, and more. All extendable.

## Stack

Python 3.11+, aiohttp, SQLite (WAL mode, aiosqlite), DeepSeek API, Hermes Agent framework. 97% test coverage.

---

## Why I'm sharing this

I've been running Santana 24/7 for weeks on a cheap VM. It manages parts of my GitHub workflow, answers questions from my chat platforms, and costs less than a streaming subscription. I think there's a real niche for **frugal autonomous agents** — agents that don't need enterprise infrastructure to be useful.

Would love feedback on:
- The memory architecture — 3 layers feels right but I'm curious if others have tried different approaches
- Tool security — the code execution runs in a restricted subprocess, but I want to harden it
- What tools would make Santana actually useful for you

**Repo:** https://github.com/BadTechResearch/santana
**Release:** https://github.com/BadTechResearch/santana/releases/tag/v2.0.0
