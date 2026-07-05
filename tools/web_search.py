"""Outils de recherche web — Serper.dev (si clé dispo) + ddgs (API DuckDuckGo officielle, gratuit)."""

import os
import logging
import requests

from ddgs import DDGS


def _serper_search(query: str) -> str | None:
    """Recherche via Serper.dev API (nécessite crédits/key)."""
    key = os.getenv("SERPER_KEY", "")
    if not key:
        return None  # Pas de clé = skip silencieux
    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "gl": "be", "hl": "fr"},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        results = r.json().get("organic", [])[:6]
        if not results:
            return None
        return "\n".join(
            f"- {x.get('title', '')}: {x.get('snippet', '')}" for x in results
        )
    except Exception as e:
        logging.warning(f"[WEB_SEARCH] Serper error: {e}")
        return None


def _ddg_search_api(query: str, max_results: int = 6) -> str | None:
    """Recherche via l'API officielle DuckDuckGo (gratuit, sans clé).

    Utilise duckduckgo_search (lib maintenue, pas de scraping HTML).
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region="fr-fr", safesearch="off", max_results=max_results))
        if not results:
            return None
        lines = []
        for r in results:
            title = r.get("title", "").strip()
            snippet = r.get("body", "").strip()
            if title:
                lines.append(f"- {title}: {snippet[:200]}" if snippet else f"- {title}")
        return "\n".join(lines) if lines else None
    except Exception as e:
        logging.warning(f"[WEB_SEARCH] DDGS API error: {e}")
        return None


def tool_web_search(query: str) -> str:
    """Effectue une recherche web (Serper.dev si clé dispo, fallback DuckDuckGo API)."""
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

        # Fallback DuckDuckGo (API officielle)
        logging.info("[WEB_SEARCH] Serper indisponible, fallback DuckDuckGo API")
        result = _ddg_search_api(query)
        if result:
            return result

        return "Aucun resultat trouve."
    except Exception as e:
        logging.error(f"[WEB_SEARCH] error: {e}")
        return "Outil temporairement indisponible"
