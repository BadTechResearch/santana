# Draft Reddit — r/LocalLLaMA

> Titre : Santana — an autonomous AI agent using DeepSeek V4 Flash for <$10/mo inference (94-96% cache hit rate, no GPU needed)

---

I built an autonomous AI agent called **Santana** that uses DeepSeek V4 Flash as its primary LLM. After running it for weeks, here are the real numbers:

## Cost breakdown

DeepSeek V4 Flash costs $0.028/1M tokens cached (output) and $0.07/1M uncached. With careful prompt engineering and a context cache that hits 94-96% of the time, my actual spend is **~$8-10/mo** for roughly 1M tokens/day.

Comparable Claude Sonnet 4 usage would cost ~$80/mo. GPT-4o ~$150/mo.

The agent also has a fallback chain (OpenRouter → Nous Portal) so if DeepSeek is down, it keeps running.

## Architecture

The agent runs on a single GCP e2-micro VM (2GB RAM, no GPU). The embedding model is all-MiniLM-L6-v2 (80MB, runs on CPU — no GPU needed).

**Memory system (3 layers):**
1. Session buffer (sliding window of current conversation)
2. Text summaries (compressed history)
3. SQLite vector store (semantic retrieval)

This lets the agent remember things across days and platforms — I can ask it on Discord about something we discussed on Telegram yesterday.

**Tools:**
- Web search (Google + social via Serper API)
- GitHub read/write
- Sandboxed Python execution
- YouTube/Twitter search
- MCP client
- Cost governor that auto-throttles

## Why DeepSeek?

1. **Cost**: $0.028/1M cached tokens is 10-20x cheaper than GPT-4o
2. **Cache hit rate**: 94-96% for agentic workloads with structured prompts
3. **Performance**: V4 Flash is surprisingly capable for tool use and reasoning
4. **No rate limit hassle**: Far fewer 429 errors than OpenAI free tier

## Trade-offs

- DeepSeek is slightly worse at creative/OpenAI-style tasks (irrelevant for an agent running tools)
- You need to structure prompts to maximize cache hits (static system prompts + variable user messages)
- No image input (but the agent doesn't need it)

## Repo

https://github.com/BadTechResearch/santana

Questions about the setup, code, or costs? Happy to share details.
