# 🦞 Santana — Autonomous AI Agent

> *"An agent that sees, remembers, learns, and improves itself."*

**Santana** is a production-ready autonomous AI agent built for real-world conversations. Unlike simple chatbots, Santana maintains a persistent memory, searches the web, analyzes images, transcribes voice, manages GitHub repos, interacts via Telegram, and continuously learns from every interaction.

Built entirely in Python by **Serge** (BadTechResearch).

---

## ✨ Features

| Capability | Description |
|---|---|
| 🧠 **Conversational AI** | Powered by DeepSeek V4 Flash (or your LLM), with streaming responses |
| 💾 **4-Layer Memory** | Session buffer + summaries + vector embeddings (MiniLM) + causal Atlas memory |
| 🌐 **Web Search** | Real-time Google search via Serper API |
| 👁️ **Vision** | Image analysis via DeepInfra Qwen3-VL (with HuggingFace + CLIP fallbacks) |
| 🎤 **Voice Transcription** | Local Whisper (tiny) — fast, private, offline |
| 🐙 **GitHub Integration** | Read/write repos, manage files, auto-commit |
| 🛠️ **Tool System** | 20+ extensible tools (web, social search, MCP, terminal, sandboxed execution) |
| 🔄 **Auto-Improvement** | `@track()` decorator monitors every tool call; self-healing engine detects patterns and suggests patches |
| 📊 **Live Dashboard** | Real-time stats via Telegram WebApp |
| 🧪 **Test Suite** | 254 pytest tests — `tests/test_system_integrity.py` (93 tests) is the reference suite for real system integrity (imports, config, routes, registry), on top of 161 unit tests |
| 🔒 **Secure VM** | Whitelist-based command execution (~60 allowed, 15 blocked, 13 dangerous patterns) |

---

## 🏗️ Architecture

```
santana/
├── core/                  # Engine: react_loop, DB singleton, utils
├── tools/                 # 20+ tools: web, vision, GitHub, MCP, terminal
├── atlas_engine/          # Persistent memory: embeddings, classifier, injector
├── memory/                # SQLite memory layer
├── tg_handlers/           # Telegram bot: commands, messages, media, brainstorm
├── self_heal/             # Auto-improvement: metrics, review, patches
├── metrics/               # Tool call tracking & error monitoring
├── routes/                # Flask API routes (dashboard, chat, system)
├── scripts/               # CI/CD, security audit, deployment
├── soul/                  # System prompts (SOUL.md, RULES.md, USER.md)
└── tests/                 # 254 pytest tests (test_system_integrity.py = reference suite)
```

**~11,000 lines of Python** across 46 files.

---

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/BadTechResearch/santana
cd santana

# 2. Install
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env with your API keys (DeepSeek, Telegram bot token, Serper)

# 4. Run
python santana.py
```

### Minimum Requirements
- Python 3.10+
- 2 GB RAM (basic operation)
- 500 MB disk
- Telegram bot token (from @BotFather)

---

## 💬 Telegram Commands

| Command | Description |
|---|---|
| `/start` | Agent status & tool list |
| `/status` | Full system dashboard |
| `/atlas on/off` | Toggle persistent learning |
| `/livres` | Browse memory books |
| `/flux` | Activity feed |
| `/brainstorm` | Enter brainstorming mode |
| `/codex` | Open Codex WebApp |
| `/help` | Show all commands |

---

## 📜 License

**GNU Affero General Public License v3.0 (AGPL-3.0)**

This license ensures Santana remains free and open — any modified version deployed as a service must also be open source.

---

## 🤝 Commercial Use

Need a dedicated Santana instance for your organization?  
Custom features? Private deployment with premium capabilities?

→ **Contact:** [@Serge](https://t.me/Serge) on Telegram

---

## 🙏 Acknowledgements

Built with ❤️ from Belgium and Kinshasa — part of the [BadTechResearch](https://github.com/BadTechResearch) ecosystem.

---

<p align="center">
  <sub>Santana learns. Santana sees. Santana grows.</sub>
</p>
