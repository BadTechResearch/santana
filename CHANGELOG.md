# Changelog

## v2.0.0 — 2026-07-05

> First public release. Santana est un agent AI autonome, frugal et multi-plateforme, construit sur le framework Hermes Agent.

### 🚀 Nouvelles fonctionnalités

- **🧠 Agent conversationnel complet** avec DeepSeek V4 Flash + chaîne de fallback (OpenRouter → Nous Portal)
- **💾 Mémoire persistante 3 couches** : buffer de session → résumés → embeddings vectoriels SQLite (all-MiniLM-L6-v2)
- **🌐 Recherche web temps réel** via Serper API (Google + réseaux sociaux)
- **🐙 Intégration GitHub** : lecture/écriture de repos, gestion de fichiers, vérification des limites API
- **🔧 15+ outils extensibles** : exécution de code sandboxée, terminal whitelisté, MCP, YouTube, Twitter
- **💰 Cost Governor** : alertes/ralentissement/arrêt selon des seuils configurables
- **🔄 Auto-analyse dynamique** (`self.py`) — l'agent connaît son propre code, ses outils et son prompt
- **🔒 Sécurité** : whitelist de commandes, terminal restreint, protection `.env`
- **📡 Multi-plateforme** : Telegram, Discord, API REST — boucle agent unifiée
- **🧪 Suite de tests** : suite complète de tests unitaires + test_system_integrity.py

### 🛠️ Infrastructure

- Stockage 100% SQLite + filesystem — zéro dépendance Docker/Redis/PostgreSQL
- Petit modèle d'embedding (all-MiniLM-L6-v2, 80MB, CPU)
- Gestionnaire de coûts en temps réel avec alerte Telegram
- Architecture asynchrone (aiohttp) pour faible latence

### 📖 Documentation

- README avec badges, arborescence et quickstart
- ARCHITECTURE.md — documentation technique complète
- CONTRIBUTING.md — guide contribution open-source
- SECURITY.md — politique de sécurité
- docs/README.md — index de la documentation
