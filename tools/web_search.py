"""Outil de recherche web via Serper.dev (fallback DuckDuckGo si épuisé)."""

import os
import logging
import requests

from metrics import track


@track()
def _serper_search(query: str) -> str:
    """Recherche via Serper.dev API (nécessite crédits)."""
    key = os.getenv("SERPER_KEY", "")
    r = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query, "gl": "be", "hl": "fr"},
        timeout=10,
    )
    if r.status_code != 200:
        return None  # Fallback silencieux
    results = r.json().get("organic", [])[:6]
    if not results:
        return None
    return "\n".join(
        f"- {x.get('title', '')}: {x.get('snippet', '')}" for x in results
    )


@track()
def _ddg_search(query: str) -> str:
    """Recherche via DuckDuckGo HTML (gratuit, sans clé)."""
    r = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; SantanaBTR/1.0)"
        },
        timeout=15,
    )
    if r.status_code != 200:
        return None
    # Extraction simple : chaque résultat est dans un bloc <a class="result__a">
    results = []
    for line in r.text.split("\n"):
        if 'class="result__a"' in line:
            # Extraire titre
            import re
            title = re.sub(r'<[^>]+>', '', line).strip()
            if title and title not in results:
                results.append(title[:120])
        if len(results) >= 6:
            break
    if not results:
        return None
    return "\n".join(f"- {r}" for r in results)


def tool_web_search(query: str) -> str:
    """Effectue une recherche web (Serper.dev, fallback DuckDuckGo)."""
    try:
        # F8 — Audit souveraineté temps réel
        try:
            from agent.souverainete import surveiller_appel_externe
            surveiller_appel_externe("https://google.serper.dev/search", "web_search")
        except Exception:
            pass

        # Essai Serper d'abord
        result = _serper_search(query)
        if result:
            return result

        # Fallback DuckDuckGo
        logging.info("[WEB_SEARCH] Serper epuise, fallback DuckDuckGo")
        result = _ddg_search(query)
        if result:
            return result

        return "Aucun resultat trouve."
    except Exception as e:
        logging.error(f"[WEB_SEARCH] error: {e}")
        return "Outil temporairement indisponible"
