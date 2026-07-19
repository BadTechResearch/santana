"""Outils de navigation web basés sur Playwright.
Remplace l'ancien endpoint MCP 5200 (serveur externe).
Playwright = moteur Chromium headless intégré, sans dépendance externe."""

import os
import logging
import tempfile
import time
from typing import Optional
from core.utils import get_base_dir

BASE_DIR = get_base_dir()
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")

# ─── Cache du navigateur (réutilisé entre les appels) ─────────────────────
_BROWSER = None
_CONTEXT = None
_PAGE = None
_BROWSER_LAST_ACTIVE = 0      # Timestamp dernière utilisation (pour idle timeout)
_BROWSER_IDLE_TIMEOUT = 300    # 5 min d'inactivité → fermeture automatique


def _get_page():
    """Retourne une page Playwright réutilisable (lazy init)."""
    global _BROWSER, _CONTEXT, _PAGE, _BROWSER_LAST_ACTIVE

    # Idle timeout : fermer le browser s'il est inactif depuis trop longtemps
    if _BROWSER is not None and time.time() - _BROWSER_LAST_ACTIVE > _BROWSER_IDLE_TIMEOUT:
        logging.info(f"[BROWSER] Idle timeout ({_BROWSER_IDLE_TIMEOUT}s) — fermeture")
        _cleanup()

    if _PAGE is not None:
        # Vérifier que la page est encore ouverte
        try:
            _PAGE.title()
            return _PAGE
        except Exception:
            logging.info("[BROWSER] Page fermée, nettoyage avant réinitialisation...")
            _cleanup()  # ← FERME proprement l'ancien navigateur avant d'en créer un nouveau

    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        _BROWSER = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        _CONTEXT = _BROWSER.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
            locale="fr-FR",
        )
        _PAGE = _CONTEXT.new_page()
        logging.info("[BROWSER] Navigateur initialisé (Chromium headless)")
        _BROWSER_LAST_ACTIVE = time.time()
        return _PAGE
    except Exception as e:
        logging.error(f"[BROWSER] Échec initialisation: {e}")
        return None


def browser_navigate(url: str, timeout: int = 30) -> str:
    """Ouvre une URL et retourne le contenu textuel de la page.

    Args:
        url: URL complète à ouvrir (https://...)
        timeout: Timeout en secondes (défaut: 30, max: 60)

    Returns:
        Texte extrait de la page (titre + body text, max 8000 chars)
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    t = min(int(timeout), 60)

    page = _get_page()
    if page is None:
        return "Erreur: navigateur non disponible (Playwright non initialisé)"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=t * 1000)
        # Attendre un peu pour le contenu dynamique
        page.wait_for_timeout(1500)

        title = page.title()
        # Extraire le texte visible
        text = page.evaluate("""() => {
            const selectors = ['article', 'main', '[role="main"]', '.content', '#content', 'body'];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.textContent.trim().length > 200) {
                    return el.textContent;
                }
            }
            return document.body ? document.body.innerText : '';
        }""")

        # Nettoyer
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        cleaned = " ".join(lines)
        # Limiter la taille
        max_len = 8000
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len] + "\n\n[... tronqué ...]"

        result = f"[{title}]\n{cleaned}" if title else cleaned
        logging.info(f"[BROWSER] Navigué: {url} → {len(cleaned)} chars")
        _BROWSER_LAST_ACTIVE = time.time()
        return result

    except Exception as e:
        err = str(e)
        logging.error(f"[BROWSER] Erreur navigation {url}: {err[:200]}")
        # Timeout commun → message clair
        if "timeout" in err.lower() or "Timeout" in err:
            return f"Erreur: timeout sur {url} (la page est peut-être trop lourde ou inaccessible)"
        return f"Erreur navigation {url}: {err[:300]}"


def browser_screenshot(url: str, timeout: int = 35) -> str:
    """Prend une capture d'écran d'une URL.

    Args:
        url: URL complète à capturer
        timeout: Timeout en secondes (défaut: 35, max: 60)

    Returns:
        Chemin du fichier PNG généré
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    t = min(int(timeout), 60)

    page = _get_page()
    if page is None:
        return "Erreur: navigateur non disponible (Playwright non initialisé)"

    try:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

        page.goto(url, wait_until="domcontentloaded", timeout=t * 1000)
        page.wait_for_timeout(2000)

        # Nom de fichier basé sur l'URL
        safe_name = url.replace("https://", "").replace("http://", "")
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in safe_name)[:60]
        path = os.path.join(SCREENSHOT_DIR, f"{safe_name}.png")

        page.screenshot(path=path, full_page=False)
        logging.info(f"[BROWSER] Screenshot: {url} → {path}")
        _BROWSER_LAST_ACTIVE = time.time()
        return f"Capture: {path}"

    except Exception as e:
        err = str(e)
        logging.error(f"[BROWSER] Erreur screenshot {url}: {err[:200]}")
        if "timeout" in err.lower():
            return f"Erreur: timeout capture {url}"
        return f"Erreur screenshot {url}: {err[:300]}"


# ─── Nettoyage à l'arrêt (optionnel, Santana ne s'arrête jamais vraiment) ──
def _cleanup():
    global _BROWSER, _CONTEXT, _PAGE
    try:
        if _BROWSER:
            _BROWSER.close()
    except Exception:
        pass
    _BROWSER = None
    _CONTEXT = None
    _PAGE = None
