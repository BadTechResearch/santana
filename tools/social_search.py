"""Recherche sociale pour Santana — Hybride Xpoz SDK + fallback frugal.

Hiérarchie :
  1. Xpoz SDK (Twitter, Reddit, Instagram, TikTok) — 2 500 crédits gratuits
  2. DuckDuckGo site: (fallback si Xpoz indisponible)
  3. Google News RSS (actualités sociales, sans clé)
  4. Playwright (URLs utilisateur uniquement)

Coûts Xpoz (plan Free) :
  Twitter  : 2 crédits/req   → ~1 250 recherches
  Reddit   : 2 crédits/req   → ~1 250 recherches
  TikTok   : 5 crédits/req   →   ~500 recherches
  Instagram: 12 crédits/req  →   ~200 recherches

Le Cost Governor peut tracker la consommation via SANTANA_CREDITS_USED.
"""

import json
import logging
import os
import urllib.parse
import urllib.request
import re
import xml.etree.ElementTree as ET
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

# Timeout pour les appels Xpoz SDK (les 44s viennent de là)
_XPOZ_TIMEOUT = 10  # secondes max par appel Xpoz
_XPOZ_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _xpoz_call_with_timeout(fn, *args, **kwargs):
    """Wrappe un appel Xpoz SDK avec timeout explicite.
    Sans ça, un appel bloquant peut prendre 44+ secondes (voir metrics.db).
    """
    future = _XPOZ_EXECUTOR.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=_XPOZ_TIMEOUT)
    except FuturesTimeout:
        logging.warning(f"[SOCIAL] Timeout {_XPOZ_TIMEOUT}s sur appel Xpoz {fn.__name__}")
        return None
    except Exception as e:
        logging.warning(f"[SOCIAL] Xpoz {fn.__name__} échec: {e}")
        return None

# ─── Xpoz SDK ─────────────────────────────────────────────────────────────

_XPOZ_CLIENT = None
_XPOZ_AVAILABLE = False
_XPOZ_KEY_SET = False


def _init_xpoz() -> bool:
    """Initialise (ou réinitialise) le client Xpoz. Thread-safe dans un contexte mono-thread."""
    global _XPOZ_CLIENT, _XPOZ_AVAILABLE, _XPOZ_KEY_SET

    if _XPOZ_CLIENT is not None:
        return _XPOZ_AVAILABLE

    api_key = os.environ.get("XPOZ_API_KEY", "").strip()
    if not api_key:
        logging.warning("[SOCIAL] XPOZ_API_KEY absente — Xpoz désactivé, fallback DDG")
        _XPOZ_AVAILABLE = False
        _XPOZ_KEY_SET = False
        return False

    _XPOZ_KEY_SET = True

    try:
        from xpoz import XpozClient
        os.environ["XPOZ_API_KEY"] = api_key  # s'assurer que le SDK le voit
        _XPOZ_CLIENT = XpozClient()
        _XPOZ_AVAILABLE = True
        logging.info(f"[SOCIAL] Xpoz SDK initialisé (clé: {api_key[:8]}...)")
        return True
    except Exception as e:
        logging.error(f"[SOCIAL] Échec init Xpoz: {e}")
        _XPOZ_CLIENT = None
        _XPOZ_AVAILABLE = False
        return False


def _xpoz_search_twitter(query: str, limit: int = 10) -> Optional[list]:
    """Recherche Twitter via Xpoz SDK. Timeout 10s. Retourne None si indisponible."""
    if not _init_xpoz():
        return None
    try:
        results = _xpoz_call_with_timeout(_XPOZ_CLIENT.twitter.search_posts, query, limit=limit)
        if results is None:
            return None
        posts = []
        for p in results.data:
            posts.append({
                "id": p.id,
                "text": p.text,
                "author": p.author_username,
                "likes": p.like_count or 0,
                "retweets": p.retweet_count or 0,
                "replies": p.reply_count or 0,
                "url": f"https://x.com/{p.author_username}/status/{p.id}",
                "date": str(p.created_at_date or ""),
                "lang": p.lang or "",
                "hashtags": p.hashtags or [],
                "mentions": p.mentions or [],
            })
        return posts
    except Exception as e:
        logging.warning(f"[SOCIAL] Xpoz Twitter échec: {e}")
        return None


def _xpoz_search_reddit(query: str, subreddit: str = "", limit: int = 10) -> Optional[list]:
    """Recherche Reddit via Xpoz SDK. Timeout 10s. Retourne None si indisponible."""
    if not _init_xpoz():
        return None
    try:
        if subreddit:
            results = _xpoz_call_with_timeout(
                _XPOZ_CLIENT.reddit.search_posts, query, subreddit=subreddit, limit=limit
            )
        else:
            results = _xpoz_call_with_timeout(_XPOZ_CLIENT.reddit.search_posts, query, limit=limit)
        if results is None:
            return None
        posts = []
        for p in results.data:
            posts.append({
                "id": p.id,
                "title": p.title,
                "text": (p.selftext or "")[:300],
                "author": p.author_username,
                "subreddit": p.subreddit_name,
                "score": p.score or 0,
                "comments": p.comments_count or 0,
                "url": p.url or "",
                "permalink": f"https://reddit.com{p.permalink}" if p.permalink else "",
                "date": str(p.created_at_date or ""),
            })
        return posts
    except Exception as e:
        logging.warning(f"[SOCIAL] Xpoz Reddit échec: {e}")
        return None


def _xpoz_search_instagram(query: str, limit: int = 10) -> Optional[list]:
    """Recherche Instagram via Xpoz SDK. Timeout 10s. Retourne None si indisponible.
    Note : Instagram coûte 12 crédits/req — utiliser avec parcimonie.
    """
    if not _init_xpoz():
        return None
    try:
        results = _xpoz_call_with_timeout(_XPOZ_CLIENT.instagram.search_posts, query, limit=limit)
        if results is None:
            return None
        posts = []
        for p in results.data:
            posts.append({
                "id": p.id,
                "type": p.post_type or "",
                "username": p.username or "",
                "caption": (p.caption or "")[:300],
                "likes": p.like_count or 0,
                "comments": p.comment_count or 0,
                "url": p.code_url or "",
                "image_url": p.image_url or "",
                "date": str(p.created_at_date or ""),
            })
        return posts
    except Exception as e:
        logging.warning(f"[SOCIAL] Xpoz Instagram échec: {e}")
        return None


def _xpoz_search_tiktok(query: str, limit: int = 10) -> Optional[list]:
    """Recherche TikTok via Xpoz SDK. Timeout 10s. Retourne None si indisponible."""
    if not _init_xpoz():
        return None
    try:
        results = _xpoz_call_with_timeout(_XPOZ_CLIENT.tiktok.search_posts, query, limit=limit)
        if results is None:
            return None
        posts = []
        for p in results.data:
            posts.append({
                "id": p.id,
                "description": (p.description or "")[:300],
                "username": p.username or "",
                "nickname": p.nickname or "",
                "likes": p.like_count or 0,
                "comments": p.comment_count or 0,
                "plays": p.play_count or 0,
                "hashtags": p.hashtags or [],
                "duration": p.duration or 0,
                "video_url": p.video_url or "",
                "date": str(p.created_at_date or ""),
            })
        return posts
    except Exception as e:
        logging.warning(f"[SOCIAL] Xpoz TikTok échec: {e}")
        return None


# ─── DuckDuckGo Fallback ──────────────────────────────────────────────────

_DDGS = None


def _get_ddgs():
    global _DDGS
    if _DDGS is not None:
        return _DDGS
    try:
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        from ddgs import DDGS
        _DDGS = DDGS()
        return _DDGS
    except Exception as e:
        logging.error(f"[SOCIAL] DDGS import échec: {e}")
        return None


def _ddg_search(query: str, max_results: int = 5) -> list:
    ddgs = _get_ddgs()
    if ddgs is None:
        return []
    try:
        results = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r.get("title", ""), "body": r.get("body", ""),
             "url": r.get("href", ""), "source": r.get("source", "")}
            for r in results
        ]
    except Exception as e:
        logging.warning(f"[SOCIAL] DDG échec: {e}")
        return []


# ─── Google News RSS ──────────────────────────────────────────────────────

_GOOGLE_NEWS_URL = "https://news.google.com/rss/search?q={q}&hl=fr&gl=FR&ceid=FR:fr"


def _google_news_rss(query: str, max_results: int = 8) -> list:
    q = urllib.parse.quote_plus(query)
    url = _GOOGLE_NEWS_URL.format(q=q)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BTR/1.0)"
        })
        resp = urllib.request.urlopen(req, timeout=10)
        xml_data = resp.read().decode("utf-8", errors="replace")
        results = []
        root = ET.fromstring(xml_data)
        for item in root.findall(".//item")[:max_results]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pubdate = item.findtext("pubDate", "")
            source = item.findtext("source", "")
            desc_raw = item.findtext("description", "")
            desc = re.sub(r"<[^>]+>", "", desc_raw)[:300] if desc_raw else ""
            results.append({
                "title": title.strip(),
                "url": link.strip(),
                "date": pubdate.strip(),
                "source": source.strip() if source else "Google News",
                "snippet": desc.strip(),
            })
        return results
    except Exception as e:
        logging.warning(f"[SOCIAL] Google News RSS échec: {e}")
        return []


# ─── Playwright Browser (URLs utilisateur uniquement) ────────────────────

_BROWSER_PAGE = None


def _browser_text(url: str, timeout: int = 20) -> str:
    global _BROWSER_PAGE
    if _BROWSER_PAGE is not None:
        try:
            _BROWSER_PAGE.title()
        except Exception:
            _BROWSER_PAGE = None
    if _BROWSER_PAGE is None:
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox",
                      "--disable-dev-shm-usage", "--disable-gpu"],
            )
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720}, locale="fr-FR",
            )
            _BROWSER_PAGE = ctx.new_page()
        except Exception as e:
            logging.error(f"[SOCIAL] Browser init échec: {e}")
            return ""
    try:
        _BROWSER_PAGE.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        _BROWSER_PAGE.wait_for_timeout(2000)
        title = _BROWSER_PAGE.title()
        text = _BROWSER_PAGE.evaluate(
            "() => document.body ? document.body.innerText : ''"
        )
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        cleaned = " ".join(lines)[:6000]
        return f"[{title}]\n{cleaned}" if title else cleaned
    except Exception as e:
        logging.warning(f"[SOCIAL] Browser échec {url}: {e}")
        return ""


# ─── Outils publics ───────────────────────────────────────────────────────

def tool_twitter_search(query_search="", max_tweets=10):
    """Cherche des tweets récents par mot-clé via Xpoz SDK (fallback DDG).

    Args:
        query_search: Termes de recherche
        max_tweets: Maximum (défaut: 10, max: 50)
    """
    n = min(int(max_tweets), 50)

    # Essai Xpoz d'abord
    xpoz_results = _xpoz_search_twitter(query_search, limit=n)
    if xpoz_results is not None:
        return json.dumps({
            "source": "Twitter (via Xpoz SDK)",
            "mode": "api",
            "count": len(xpoz_results),
            "results": xpoz_results,
        })

    # Fallback DDG
    q = f"(site:twitter.com OR site:x.com) {query_search}"
    results = _ddg_search(q, max_results=n)
    if results:
        return json.dumps({
            "source": "Twitter (via DuckDuckGo)",
            "mode": "web_search",
            "count": len(results),
            "results": results,
            "note": "Fallback DDG — Xpoz SDK indisponible."
        })

    return json.dumps({
        "note": f"Aucun tweet trouvé pour '{query_search}'.",
    })


def tool_twitter_lookup(handle="", query="", max_tweets=5):
    """Cherche les tweets d'un compte Twitter/X spécifique.

    Args:
        handle: Nom du compte Twitter (sans @)
        query: Filtre optionnel
        max_tweets: Maximum (défaut: 5, max: 50)
    """
    n = min(int(max_tweets), 50)

    # Essai Xpoz d'abord (recherche par auteur)
    xpoz_results = _xpoz_search_twitter(query or handle, limit=n)
    if xpoz_results is not None:
        # Filtrer par auteur si handle fourni
        if handle:
            xpoz_results = [p for p in xpoz_results
                            if p["author"].lower() == handle.lower()]
        return json.dumps({
            "source": f"Twitter (@{handle}) (via Xpoz SDK)",
            "mode": "api",
            "count": len(xpoz_results),
            "results": xpoz_results,
        })

    # Fallback DDG
    q_parts = []
    if handle:
        q_parts.append(f"site:twitter.com {handle}")
    if query:
        q_parts.append(query)
    q = " ".join(q_parts) if q_parts else f"site:twitter.com {handle}"
    results = _ddg_search(q, max_results=n)
    if results:
        return json.dumps({
            "source": f"Twitter (@{handle}) (via DuckDuckGo)",
            "mode": "web_search",
            "count": len(results),
            "results": results,
        })

    return json.dumps({
        "note": f"Aucun résultat Twitter pour '{query or handle}'.",
        "suggestion": "Essaie avec des termes plus précis."
    })


def tool_reddit_search(query="", subreddit="", max_posts=10):
    """Cherche des posts Reddit par mot-clé via Xpoz SDK (fallback DDG).

    Args:
        query: Termes de recherche
        subreddit: Sous-reddit spécifique (optionnel)
        max_posts: Maximum (défaut: 10, max: 50)
    """
    n = min(int(max_posts), 50)

    # Essai Xpoz d'abord
    xpoz_results = _xpoz_search_reddit(query, subreddit=subreddit, limit=n)
    if xpoz_results is not None:
        return json.dumps({
            "source": f"Reddit (via Xpoz SDK)",
            "mode": "api",
            "count": len(xpoz_results),
            "results": xpoz_results,
        })

    # Fallback DDG
    q = f"site:reddit.com {query}"
    if subreddit:
        q = f"site:reddit.com/r/{subreddit} {query}"
    results = _ddg_search(q, max_results=n)
    if results:
        return json.dumps({
            "source": f"r/{subreddit}" if subreddit else "Reddit (via DuckDuckGo)",
            "mode": "web_search",
            "count": len(results),
            "results": results,
        })

    return json.dumps({
        "note": f"Aucun résultat Reddit pour '{query}'.",
    })


def tool_reddit_lookup(subreddit="", max_posts=5):
    """Regarde les posts récents d'un subreddit."""
    n = min(int(max_posts), 50)
    return tool_reddit_search(query="", subreddit=subreddit, max_posts=n)


def tool_instagram_search(query="", max_posts=10):
    """Cherche des posts Instagram par mot-clé via Xpoz SDK (fallback DDG).

    Note : Instagram Xpoz coûte 12 crédits/req — coûteux.
    Args:
        query: Termes de recherche
        max_posts: Maximum (défaut: 10, max: 20)
    """
    n = min(int(max_posts), 20)

    # Essai Xpoz d'abord
    xpoz_results = _xpoz_search_instagram(query, limit=n)
    if xpoz_results is not None:
        return json.dumps({
            "source": "Instagram (via Xpoz SDK)",
            "mode": "api",
            "count": len(xpoz_results),
            "results": xpoz_results,
        })

    # Fallback DDG
    q = f"site:instagram.com {query}"
    results = _ddg_search(q, max_results=n)
    if results:
        return json.dumps({
            "source": "Instagram (via DuckDuckGo)",
            "mode": "web_search",
            "count": len(results),
            "results": results,
            "note": "Instagram ne permet pas le scraping sans login. Résultats via DuckDuckGo."
        })

    return json.dumps({
        "note": f"Aucun résultat Instagram pour '{query}'."
    })


def tool_instagram_lookup(username="", max_posts=5):
    """Regarde les posts publics d'un compte Instagram."""
    return tool_instagram_search(query=username, max_posts=max_posts)


def tool_tiktok_search(query="", max_posts=10):
    """Cherche des vidéos TikTok par mot-clé via Xpoz SDK (fallback DDG).

    Args:
        query: Termes de recherche
        max_posts: Maximum (défaut: 10, max: 20)
    """
    n = min(int(max_posts), 20)

    # Essai Xpoz d'abord
    xpoz_results = _xpoz_search_tiktok(query, limit=n)
    if xpoz_results is not None:
        return json.dumps({
            "source": "TikTok (via Xpoz SDK)",
            "mode": "api",
            "count": len(xpoz_results),
            "results": xpoz_results,
        })

    # Fallback DDG
    q = f"site:tiktok.com {query}"
    results = _ddg_search(q, max_results=n)
    if results:
        return json.dumps({
            "source": "TikTok (via DuckDuckGo)",
            "mode": "web_search",
            "count": len(results),
            "results": results,
        })

    return json.dumps({"note": f"Aucun résultat TikTok pour '{query}'."})


def tool_tiktok_lookup(username="", max_posts=5):
    """Regarde les vidéos d'un compte TikTok."""
    return tool_tiktok_search(query=f"@{username}", max_posts=max_posts)


def tool_social_news(query="", platform="all", max_results=8):
    """Cherche des actualités récentes sur les réseaux sociaux via Google News RSS.

    Args:
        query: Sujet de recherche
        platform: 'all' (défaut), 'twitter', 'reddit'
        max_results: Maximum (défaut: 8, max: 15)
    """
    n = min(int(max_results), 15)
    keywords = query

    if platform in ("twitter", "x"):
        keywords = f"{query} Twitter OR X"
    elif platform == "reddit":
        keywords = f"{query} Reddit"

    results = _google_news_rss(keywords, max_results=n)
    if results:
        return json.dumps({
            "source": f"Google News RSS ({platform})",
            "mode": "rss",
            "count": len(results),
            "results": results,
        })

    return json.dumps({"note": f"Aucune actualité pour '{query}'."})


def tool_social_browser(url="", timeout=20):
    """Ouvre une URL sociale spécifique avec Playwright.
    Usage réservé aux URLs fournies explicitement par l'utilisateur.
    """
    if not url.startswith(("http://", "https://")):
        return json.dumps({"error": "URL invalide. Doit commencer par http:// ou https://"})

    t = min(int(timeout), 30)
    text = _browser_text(url, timeout=t)
    if text:
        return json.dumps({
            "source": "Playwright browser",
            "url": url,
            "content_length": len(text),
            "content": text[:5000],
            "note": "Résultat du navigateur. Les plateformes sociales peuvent bloquer les IP cloud."
        })

    return json.dumps({
        "error": f"Impossible d'accéder à {url}",
        "note": "Les IP cloud sont souvent bloquées par les réseaux sociaux."
    })


# ─── Point d'entrée unifié ───────────────────────────────────────────────

def social_search(query="", platform="all", count=5):
    """Point d'entrée unique pour la recherche sociale.

    Hiérarchie :
      1. Xpoz SDK (Twitter, Reddit, Instagram, TikTok)
      2. DuckDuckGo site: (fallback)
      3. Google News RSS (actualités)

    Args:
        query: Termes de recherche
        platform: 'all', 'twitter', 'reddit', 'instagram', 'tiktok', 'news'
        count: Nombre de résultats par source (défaut: 5, max: 10)
    """
    n = min(int(count), 10)
    platform = platform.lower()
    all_results = []
    sources_used = []

    handlers = {
        "twitter": lambda: tool_twitter_search(query_search=query, max_tweets=n),
        "reddit": lambda: tool_reddit_search(query=query, max_posts=n),
        "instagram": lambda: tool_instagram_search(query=query, max_posts=n),
        "tiktok": lambda: tool_tiktok_search(query=query, max_posts=n),
        "news": lambda: tool_social_news(query=query, max_results=n),
    }

    if platform == "all":
        for plat_name in ["twitter", "reddit", "news"]:
            r = json.loads(handlers[plat_name]())
            if "results" in r and r["results"]:
                all_results.extend(r["results"])
                sources_used.append(plat_name)
    elif platform in handlers:
        r = json.loads(handlers[platform]())
        if "results" in r and r["results"]:
            all_results.extend(r["results"])
            sources_used.append(platform)

    if all_results:
        return json.dumps({
            "source": "+".join(sources_used),
            "mode": "hybrid",
            "count": len(all_results),
            "results": all_results,
        })

    return json.dumps({
        "note": f"Aucun résultat social pour '{query}'.",
        "suggestion": "Utilise web_search (DuckDuckGo) qui a un meilleur indexing du web général.",
        "mode": "empty"
    })
