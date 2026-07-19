"""Scheduler interne Santana — tâches planifiées dans le process même.

Remplace la dépendance à Hermès cron pour le backup DB et le CI.
S'exécute dans l'async loop principale de Santana (tâche background).

Schedule :
  - Backup DB  : 03:00 WAT (Africa/Kinshasa)
  - CI tests   : 06:00 WAT

Notifications Telegram envoyées directement via l'API Telegram (curl)
pour ne pas dépendre du bot Application (évite les conflits d'état).
"""

import asyncio, logging, os, subprocess, time
from datetime import datetime, timezone, timedelta

# Africa/Kinshasa = UTC+1 (pas de DST)
_WAT = timezone(timedelta(hours=1))

# ── Configuration ──
SANTANA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PYTHON = os.path.join(SANTANA_DIR, "venv_new", "bin", "python3")

# Schedule : (hour, minute) en WAT
_BACKUP_TIME = (3, 0)   # 03:00
_CI_TIME = (6, 0)       # 06:00

# Cache : éviter de relancer la même tâche plusieurs fois dans la même minute
_last_backup_day = -1
_last_ci_day = -1

_log = logging.getLogger("scheduler")


def _now_wat() -> datetime:
    """Retourne l'heure actuelle en Africa/Kinshasa (UTC+1)."""
    return datetime.now(_WAT)


def _notify_telegram(text: str):
    """Envoie un message Telegram via API directe (curl)."""
    env_path = os.path.join(SANTANA_DIR, ".env")
    token = None
    chat = None
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_TOKEN="):
                    token = line.split("=", 1)[1].strip("\"'")
                elif line.startswith("CHAT_ID="):
                    chat = line.split("=", 1)[1].strip("\"'")
    except Exception:
        _log.warning("[SCHEDULER] Impossible de lire .env pour notification")
        return
    if not token or not chat:
        return
    try:
        subprocess.run(
            ["curl", "-s", "-m", "10",
             f"https://api.telegram.org/bot{token}/sendMessage",
             "-d", f"chat_id={chat}",
             "--data-urlencode", f"text={text}"],
            capture_output=True, timeout=15,
        )
    except Exception as e:
        _log.warning("[SCHEDULER] Échec notification Telegram: %s", e)


async def _run_backup():
    """Exécute le backup DB et notifie en cas d'échec."""
    script = os.path.join(SANTANA_DIR, "scripts", "backup_db.sh")
    if not os.path.exists(script):
        _log.error("[SCHEDULER] Script backup introuvable: %s", script)
        return
    _log.info("[SCHEDULER] Backup DB — début")
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash", script,
            cwd=SANTANA_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode == 0:
            _log.info("[SCHEDULER] Backup DB ✅")
        else:
            out = stdout.decode(errors="replace")[:2000]
            err = stderr.decode(errors="replace")[:500]
            _log.error("[SCHEDULER] Backup DB ❌ (code %d)", proc.returncode)
            _notify_telegram(
                f"🔴 Santana Backup — {_now_wat().strftime('%Y-%m-%d %H:%M')}\n"
                f"❌ Échec (code {proc.returncode})\n\n{out}\n{err}"
            )
    except asyncio.TimeoutError:
        _log.error("[SCHEDULER] Backup DB — timeout 120s")
        _notify_telegram(f"🔴 Santana Backup — timeout (120s dépassé)")


async def _run_ci():
    """Exécute les tests CI et notifie en cas d'échec."""
    test_files = [
        os.path.join(SANTANA_DIR, "tests", "test_system_integrity.py"),
        os.path.join(SANTANA_DIR, "tests", "test_100_performances.py"),
    ]
    _log.info("[SCHEDULER] CI tests — début")
    try:
        proc = await asyncio.create_subprocess_exec(
            VENV_PYTHON, "-m", "pytest",
            *test_files,
            "-v", "--tb=line",
            cwd=SANTANA_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        out = stdout.decode(errors="replace")
        if proc.returncode == 0:
            _log.info("[SCHEDULER] CI tests ✅ — tous verts")
        else:
            err = stderr.decode(errors="replace")[:500]
            failed = []
            for line in out.splitlines():
                if "FAILED" in line:
                    failed.append(line.strip())
            summary = "\n".join(f"• {t}" for t in failed[:10])
            _log.error("[SCHEDULER] CI tests ❌ (code %d) — %d échecs",
                       proc.returncode, len(failed))
            _notify_telegram(
                f"🔴 Santana CI — {_now_wat().strftime('%Y-%m-%d %H:%M')}\n"
                f"❌ {len(failed)} échec(s) sur les tests\n\n"
                f"{summary}\n\n"
                f"📊 Détails : logs Santana"
            )
    except asyncio.TimeoutError:
        _log.error("[SCHEDULER] CI tests — timeout 120s")
        _notify_telegram(f"🔴 Santana CI — timeout (120s)")


async def scheduler_loop():
    """Boucle principale du scheduler — vérifie l'heure toutes les 60s.

    À intégrer comme asyncio.create_task() dans _post_init().
    """
    global _last_backup_day, _last_ci_day

    # Attendre un peu au démarrage (laisser Santana s'initialiser)
    await asyncio.sleep(30)

    _log.info("[SCHEDULER] Démarré — backup à 03:00, CI à 06:00 (Africa/Kinshasa)")

    while True:
        try:
            now = _now_wat()
            today = now.day

            # Backup à 03:00
            if now.hour == _BACKUP_TIME[0] and now.minute == _BACKUP_TIME[1]:
                if _last_backup_day != today:
                    _last_backup_day = today
                    await _run_backup()

            # CI à 06:00
            if now.hour == _CI_TIME[0] and now.minute == _CI_TIME[1]:
                if _last_ci_day != today:
                    _last_ci_day = today
                    await _run_ci()

        except Exception as e:
            _log.error("[SCHEDULER] Erreur dans la boucle: %s", e)

        await asyncio.sleep(60)
