"""Recherche sociale hiérarchique pour Santana.
Hiérarchie :
  1. web_search (Google) — gratuit, illimité, pour tout
  2. Xpoz (API native) — Twitter, Instagram, TikTok, Reddit si web_search insuffisant
"""

import os
import json
import logging

_XPOZ_KEY = os.getenv("XPOZ_API_KEY", "")
_XPOZ_CLIENT = None


def _xpoz_client():
    global _XPOZ_CLIENT
    if _XPOZ_CLIENT is not None:
        return _XPOZ_CLIENT, None
    if not _XPOZ_KEY:
        return None, "Xpoz non configuré"
    try:
        from xpoz import XpozClient
        _XPOZ_CLIENT = XpozClient(api_key=_XPOZ_KEY)
        return _XPOZ_CLIENT, None
    except Exception as e:
        return None, str(e)


def _post_to_dict(post):
    try:
        d = post.dict() if hasattr(post, 'dict') else {}
    except Exception:
        logging.error("[SOCIAL_SEARCH] _post_to_dict echec")
        d = {}
    text = d.get("text", "") or d.get("caption", "") or d.get("title", "") or getattr(post, "text", "") or ""
    created = d.get("created_at", "") or d.get("created_at_date", "") or d.get("date", "") or getattr(post, "created_at_date", "") or ""
    author = d.get("author_username", "") or d.get("username", "") or getattr(post, "author_username", "") or ""
    return {"text": text[:500], "date": created, "author": author}


# ─── Fonctions exposées (appelables par le LLM) ────────────────────────────

def tool_twitter_lookup(handle="", query="", max_tweets=5, search_url=""):
    return json.dumps({"info": "Utilise web_search (Google) pour les recherches Twitter par défaut. Xpoz est utilisé uniquement si web_search ne donne pas de résultats pertinents."})


def tool_twitter_search(query_search="", max_tweets=10):
    return json.dumps({"info": "Utilise web_search (Google) pour les recherches Twitter par défaut. Xpoz est utilisé uniquement si web_search ne donne pas de résultats pertinents."})


def tool_instagram_lookup(username="", max_posts=5):
    return json.dumps({"info": "Utilise web_search (Google) pour les recherches Instagram par défaut."})


def tool_instagram_search(query="", max_posts=10):
    return json.dumps({"info": "Utilise web_search (Google) pour les recherches Instagram par défaut."})


def tool_tiktok_lookup(username="", max_posts=5):
    return json.dumps({"info": "Utilise web_search (Google) pour les recherches TikTok par défaut."})


def tool_tiktok_search(query="", max_posts=10):
    return json.dumps({"info": "Utilise web_search (Google) pour les recherches TikTok par défaut."})


def tool_reddit_lookup(subreddit="", max_posts=5):
    return json.dumps({"info": "Utilise web_search (Google) pour les recherches Reddit par défaut."})


def tool_reddit_search(query="", max_posts=10):
    return json.dumps({"info": "Utilise web_search (Google) pour les recherches Reddit par défaut."})


# ─── Fonctions Xpoz (appel direct quand web_search ne suffit pas) ───────────

def xpoz_twitter_lookup(handle="", query="", max_results=5):
    """Recherche Twitter native via Xpoz (fallback)."""
    client, err = _xpoz_client()
    if err:
        return {"error": err}
    try:
        result = client.twitter.get_posts_by_author(handle, limit=min(max_results, 50))
        posts = list(result.data)
        if not posts:
            return {"error": f"Rien pour @{handle}"}
        if query:
            q = query.lower()
            posts = [p for p in posts if q in (p.text or "").lower()]
        return {"source": "Twitter (Xpoz)", "count": len(posts[:max_results]), "results": [_post_to_dict(p) for p in posts[:max_results]]}
    except Exception as e:
        return {"error": str(e)}


def xpoz_twitter_search(query="", max_results=10):
    client, err = _xpoz_client()
    if err:
        return {"error": err}
    try:
        result = client.twitter.search_posts(query, limit=min(max_results, 50))
        posts = list(result.data)
        if not posts:
            return {"error": f"Rien trouvé: {query}"}
        return {"source": "Twitter (Xpoz)", "count": len(posts[:max_results]), "results": [_post_to_dict(p) for p in posts[:max_results]]}
    except Exception as e:
        return {"error": str(e)}


def xpoz_instagram_lookup(username="", max_results=5):
    client, err = _xpoz_client()
    if err:
        return {"error": err}
    try:
        result = client.instagram.get_posts_by_user(username, limit=min(max_results, 20))
        posts = list(result.data)
        if not posts:
            return {"error": f"Rien pour @{username}"}
        return {"source": "Instagram (Xpoz)", "count": len(posts[:max_results]), "results": [_post_to_dict(p) for p in posts[:max_results]]}
    except Exception as e:
        return {"error": str(e)}


def xpoz_tiktok_lookup(username="", max_results=5):
    client, err = _xpoz_client()
    if err:
        return {"error": err}
    try:
        result = client.tiktok.get_posts_by_user(username, limit=min(max_results, 20))
        posts = list(result.data)
        if not posts:
            return {"error": f"Rien pour @{username}"}
        return {"source": "TikTok (Xpoz)", "count": len(posts[:max_results]), "results": [_post_to_dict(p) for p in posts[:max_results]]}
    except Exception as e:
        return {"error": str(e)}


def xpoz_reddit_lookup(subreddit="", max_results=5):
    client, err = _xpoz_client()
    if err:
        return {"error": err}
    try:
        result = client.reddit.get_subreddit_with_posts(subreddit)
        posts = list(result.data)
        if not posts:
            return {"error": f"r/{subreddit} vide"}
        return {"source": "Reddit (Xpoz)", "count": len(posts[:max_results]), "results": [_post_to_dict(p) for p in posts[:max_results]]}
    except Exception as e:
        return {"error": str(e)}


def social_search(query="", platform="all", count=5):
    """Point d'entrée unique pour la recherche sociale hiérarchique.
    Hiérarchie : 1. web_search (Google) — déjà fait par l'appelant LLM
                 2. Xpoz (API native) — fallback uniquement"""
    count = int(count)
    platform = platform.lower()
    results = []

    if platform in ("all", "twitter"):
        r = xpoz_twitter_lookup(query, max_results=count) if not query.startswith("@") else xpoz_twitter_lookup(handle=query.lstrip("@"), max_results=count)
        if isinstance(r, dict) and "error" not in r:
            results.append(r)
    if platform in ("all", "instagram"):
        r = xpoz_instagram_lookup(username=query.lstrip("@"), max_results=count)
        if isinstance(r, dict) and "error" not in r:
            results.append(r)
    if platform in ("all", "tiktok"):
        r = xpoz_tiktok_lookup(username=query.lstrip("@"), max_results=count)
        if isinstance(r, dict) and "error" not in r:
            results.append(r)
    if platform in ("all", "reddit"):
        r = xpoz_reddit_lookup(subreddit=query, max_results=count)
        if isinstance(r, dict) and "error" not in r:
            results.append(r)

    if not results:
        return json.dumps({"note": "Xpoz n'a pas retourné de résultats. Utilise web_search (Google) à la place.", "platform": platform})
    return json.dumps({"source": "Xpoz", "platform": platform, "results": results})
