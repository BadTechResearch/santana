#!/usr/bin/env python3
"""
Veille Tech & Agentic Daily v2 — Script de collecte.

Utilise feedparser (RSS), GitHub API, Hugging Face API,
et le browser Playwright pour les sites qui marchent bien.

Usage: python3 scripts/veille_tech.py [--no-browser]
  --no-browser: skip Playwright (RSS + APIs uniquement)

Output: JSON structuré vers stdout, délimité par === DATA === et === END ===
"""

import sys, os, json, time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SANTANA_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, SANTANA_DIR)

USE_BROWSER = "--no-browser" not in sys.argv

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ─── RSS Google News ──────────────────────────────────────────────
RSS_FEEDS = {
    "tech_ia_monde": {
        "url": "https://news.google.com/rss/search?q=artificial+intelligence+AI+technology+2026&hl=fr&gl=FR&ceid=FR:fr",
        "max": 6,
    },
    "agents_ia": {
        "url": "https://news.google.com/rss/search?q=AI+agent+framework+autonomous+agent+open+source&hl=fr&gl=FR&ceid=FR:fr",
        "max": 5,
    },
    "llm_open_source": {
        "url": "https://news.google.com/rss/search?q=open+source+LLM+language+model+release+2026&hl=fr&gl=FR&ceid=FR:fr",
        "max": 5,
    },
    "rdc_tech_eco": {
        "url": "https://news.google.com/rss/search?q=RDC+R%C3%A9publique+d%C3%A9mocratique+du+Congo+technologie+num%C3%A9rique+startup&hl=fr&gl=FR&ceid=FR:fr",
        "max": 6,
    },
    "rdc_evenements": {
        "url": "https://news.google.com/rss/search?q=RDC+Congo+%C3%A9v%C3%A9nement+forum+conf%C3%A9rence+tech+entrepreneuriat+%C3%A0+venir&hl=fr&gl=FR&ceid=FR:fr",
        "max": 6,
    },
    "claude_anthropic": {
        "url": "https://news.google.com/rss/search?q=Claude+Code+Anthropic+AI+agent&hl=fr&gl=FR&ceid=FR:fr",
        "max": 4,
    },
    "hermes_nous": {
        "url": "https://news.google.com/rss/search?q=Nous+Research+Hermes+Agent+open+source&hl=fr&gl=FR&ceid=FR:fr",
        "max": 4,
    },
}

# ─── Sites accessibles via browser Playwright ─────────────────────
SITES_BROWSER = {
    "nous_research": ("https://nousresearch.com/", "Actualités Nous Research / Hermes Agent"),
    "actualite_cd": ("https://actualite.cd/", "Actualités RDC (Actualite.CD)"),
    "radio_okapi": ("https://www.radiookapi.net/", "Actualités RDC (Radio Okapi)"),
    "digital_congo": ("https://www.digitalcongo.net/", "Tech RDC (Digital Congo)"),
}

# ─── GitHub API Search ────────────────────────────────────────────
GITHUB_QUERIES = [
    # Agents / frameworks agentiques
    ("agentic framework stars:>1000", "agents_frameworks", 8),
    ("topic:ai-agent stars:>500", "ai_agent_topic", 8),
    ("ai agent autonomous 2026", "ai_agent_general", 6),
    # Nous Research
    ("Nous Research Hermes", "nous_hermes", 5),
    # Claude Code
    ("Claude Code Anthropic", "claude_code", 5),
    # OpenClaw (peu de résultats mais on cherche)
    ("OpenClaw AI agent", "openclaw", 5),
    # LLM open source récents
    ("open source LLM released 2026", "llm_2026", 6),
]

def parse_rss(url, max_items=5):
    try:
        import feedparser
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:max_items]:
            items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": entry.get("source", {}).get("title", "") if hasattr(entry, "source") else "",
                "summary": (entry.get("summary", "") or "")[:300],
            })
        return items
    except Exception as e:
        return [{"error": f"RSS: {e}"}]

def fetch_via_browser(url):
    if not USE_BROWSER:
        return {"error": "Browser désactivé", "content": ""}
    try:
        sys.path.insert(0, os.path.join(SANTANA_DIR, "tools"))
        from browser import browser_navigate
        content = browser_navigate(url, timeout=30)
        return {"content": content[:4000], "source": url}
    except Exception as e:
        return {"error": str(e)[:200], "content": ""}

def search_github(query, label, max_results=8):
    """Cherche des repos via GitHub API search."""
    results = []
    try:
        import requests
        url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page={max_results}"
        r = requests.get(url, headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Hermes-Cron/1.0",
        }, timeout=15)
        if r.status_code == 200:
            data = r.json()
            for item in data.get("items", [])[:max_results]:
                results.append({
                    "name": item["full_name"],
                    "stars": item["stargazers_count"],
                    "description": (item.get("description") or "")[:200],
                    "url": item["html_url"],
                    "language": item.get("language") or "",
                    "updated": item.get("updated_at", ""),
                })
        else:
            results.append({"error": f"HTTP {r.status_code}", "query": query})
    except Exception as e:
        results.append({"error": str(e)[:200], "query": query})
    return {label: results}

def fetch_hf_models():
    """Top LLMs téléchargés sur Hugging Face."""
    try:
        import requests
        # Top modèles text-generation
        r1 = requests.get(
            "https://huggingface.co/api/models?sort=downloads&direction=-1&search=llm&limit=8",
            timeout=15,
        )
        # Top trending récents
        r2 = requests.get(
            "https://huggingface.co/api/models?sort=trending&direction=-1&search=llm&limit=8",
            timeout=15,
        )
        models = []
        seen_ids = set()
        for resp in [r1, r2]:
            if resp.status_code == 200:
                for m in resp.json():
                    mid = m.get("modelId", m.get("id", ""))
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                    models.append({
                        "id": mid,
                        "downloads": m.get("downloads", 0),
                        "likes": m.get("likes", 0),
                        "pipeline": m.get("pipeline_tag", ""),
                    })
        return models[:15]
    except Exception as e:
        return [{"error": f"HF: {e}"}]

# ─── Collecte principale ──────────────────────────────────────────
def collect():
    results = {
        "timestamp": datetime.now().isoformat(),
        "sections": {},
    }
    print(f"🔍 Veille Tech — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"   Browser: {'ACTIF' if USE_BROWSER else 'DÉSACTIVÉ'}")
    print()

    # 1. RSS (parallèle)
    print("📡 [1/4] Flux RSS…")
    rss_out = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        fut = {pool.submit(parse_rss, v["url"], v["max"]): k for k, v in RSS_FEEDS.items()}
        for f in as_completed(fut):
            rss_out[fut[f]] = f.result()
    results["sections"]["rss"] = rss_out

    # 2. GitHub API (parallèle)
    print("🐙 [2/4] GitHub API…")
    gh_out = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        fut = {pool.submit(search_github, q, l, m): l for q, l, m in GITHUB_QUERIES}
        for f in as_completed(fut):
            gh_out.update(f.result())
    results["sections"]["github"] = gh_out

    # 3. Hugging Face
    print("🤗 [3/4] Hugging Face…")
    results["sections"]["huggingface"] = fetch_hf_models()

    # 4. Browser (pages dynamiques)
    if USE_BROWSER:
        print("🌐 [4/4] Browser…")
        browser_out = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            fut = {pool.submit(fetch_via_browser, url): label for url, label in SITES_BROWSER.values()}
            for f in as_completed(fut):
                browser_out[fut[f]] = f.result()
        results["sections"]["browser"] = browser_out
    else:
        results["sections"]["browser"] = {}

    return results


if __name__ == "__main__":
    data = collect()
    print()
    print("=== DATA ===")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("=== END ===")
