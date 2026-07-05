#!/usr/bin/env python3
"""
Cost Governor — compteur léger de crédits/tokens par tâche pour Santana (Black Intelligence).

Utilise workspace_state SQLite via le helper intégré de Santana.
Usage :
    python3 cost_governor.py status
    python3 cost_governor.py init <task_name> [--token-budget N] [--xpoz-budget N]
    python3 cost_governor.py track <task_name> --tokens N [--xpoz N]
    python3 cost_governor.py check <task_name>
    python3 cost_governor.py close <task_name>
    python3 cost_governor.py history
"""

import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime
from core.utils import get_base_dir

BASE_DIR = get_base_dir()
DB_PATH = os.path.join(BASE_DIR, "data", "workspace.db")
MAX_HISTORY = 100  # garder les 100 derniers enregistrements


def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS ws (
        key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS cost_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task TEXT, tokens INTEGER, xpoz INTEGER,
        budget_tokens INTEGER, budget_xpoz INTEGER,
        decision TEXT, note TEXT, created_at TEXT
    )""")
    conn.commit()
    return conn


def _ws_get(key: str, default: str = "") -> str:
    conn = _get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM ws WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default


def _ws_set(key: str, value: str):
    conn = _get_db()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO ws (key, value, updated_at) VALUES (?, ?, ?)",
        (key, value, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def _log_history(task: str, tokens: int, xpoz: int,
                 budget_tokens: int, budget_xpoz: int,
                 decision: str, note: str = ""):
    conn = _get_db()
    c = conn.cursor()
    c.execute(
        """INSERT INTO cost_history
           (task, tokens, xpoz, budget_tokens, budget_xpoz, decision, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (task, tokens, xpoz, budget_tokens, budget_xpoz, decision, note, datetime.now().isoformat()),
    )
    # Nettoyer l'historique trop vieux
    c.execute(
        "DELETE FROM cost_history WHERE id NOT IN (SELECT id FROM cost_history ORDER BY id DESC LIMIT ?)",
        (MAX_HISTORY,),
    )
    conn.commit()
    conn.close()


def cmd_status():
    """Affiche l'état actuel du Cost Governor."""
    raw = _ws_get("cg_active_tasks", "{}")
    try:
        tasks = json.loads(raw)
    except json.JSONDecodeError:
        tasks = {}

    if not tasks:
        print("📊 Cost Governor — Aucune tâche active\n")
    else:
        print(f"📊 Cost Governor — {len(tasks)} tâche(s) active(s)\n")
        for name, data in tasks.items():
            print(f"  ── {name}")
            print(f"     Tokens : {data.get('tokens', 0)} / {data.get('budget_tokens', '∞')}")
            print(f"     Xpoz   : {data.get('xpoz', 0)} / {data.get('budget_xpoz', '∞')}")
            ratio_t = data['tokens'] / data['budget_tokens'] * 100 if data.get('budget_tokens', 0) > 0 else 0
            ratio_x = data['xpoz'] / data['budget_xpoz'] * 100 if data.get('budget_xpoz', 0) > 0 else 0
            print(f"     Ratio  : {ratio_t:.0f}% tokens, {ratio_x:.0f}% crédits Xpoz")
            print()

    # Dernières entrées de l'historique
    conn = _get_db()
    c = conn.cursor()
    c.execute(
        "SELECT task, tokens, xpoz, decision, created_at FROM cost_history ORDER BY id DESC LIMIT 5"
    )
    rows = c.fetchall()
    conn.close()
    if rows:
        print("Dernières actions :")
        for r in rows:
            print(f"  [{r[4]}] {r[0]} : {r[3]} ({r[1]} tokens, {r[2]} Xpoz)")


def cmd_init(task: str, budget_tokens: int = 0, budget_xpoz: int = 0):
    """Initialise le budget pour une tâche."""
    raw = _ws_get("cg_active_tasks", "{}")
    try:
        tasks = json.loads(raw)
    except json.JSONDecodeError:
        tasks = {}

    if task in tasks:
        print(f"⚠️  Tâche '{task}' déjà active. Utilise 'close' d'abord ou 'track' pour ajouter.")
        return

    tasks[task] = {
        "tokens": 0,
        "xpoz": 0,
        "budget_tokens": budget_tokens,
        "budget_xpoz": budget_xpoz,
        "started_at": datetime.now().isoformat(),
    }
    _ws_set("cg_active_tasks", json.dumps(tasks))
    _log_history(task, 0, 0, budget_tokens, budget_xpoz, "init",
                 f"Budget alloué : {budget_tokens} tokens, {budget_xpoz} Xpoz")
    print(f"✅ Tâche '{task}' initialisée")
    print(f"   Budget tokens : {'∞' if budget_tokens == 0 else budget_tokens}")
    print(f"   Budget Xpoz   : {'∞' if budget_xpoz == 0 else budget_xpoz}")


def cmd_track(task: str, tokens: int = 0, xpoz: int = 0):
    """Ajoute des coûts à une tâche active."""
    raw = _ws_get("cg_active_tasks", "{}")
    try:
        tasks = json.loads(raw)
    except json.JSONDecodeError:
        tasks = {}

    if task not in tasks:
        print(f"❌ Tâche '{task}' introuvable. Utilise 'init' d'abord.")
        return

    data = tasks[task]
    data["tokens"] += tokens
    data["xpoz"] += xpoz
    tasks[task] = data
    _ws_set("cg_active_tasks", json.dumps(tasks))

    # Vérifier les seuils
    warnings = []
    if data["budget_tokens"] > 0 and data["tokens"] >= data["budget_tokens"]:
        warnings.append(f"⚠️  BUDGET TOKENS ATTEINT ({data['tokens']}/{data['budget_tokens']})")
    if data["budget_xpoz"] > 0 and data["xpoz"] >= data["budget_xpoz"]:
        warnings.append(f"⚠️  BUDGET XPOZ ATTEINT ({data['xpoz']}/{data['budget_xpoz']})")

    decision = "ok"
    note = f"+{tokens} tokens, +{xpoz} Xpoz"
    if warnings:
        decision = "budget_exceeded"
        note += " | " + " | ".join(warnings)

    _log_history(task, data["tokens"], data["xpoz"],
                 data["budget_tokens"], data["budget_xpoz"],
                 decision, note)

    print(f"📝 {task} : {tokens} tokens, {xpoz} Xpoz ajoutés")
    print(f"   Total : {data['tokens']} / {data['budget_tokens']} tokens, "
          f"{data['xpoz']} / {data['budget_xpoz']} Xpoz")
    for w in warnings:
        print(f"   {w}")


def cmd_check(task: str):
    """Vérifie si la tâche peut continuer."""
    raw = _ws_get("cg_active_tasks", "{}")
    try:
        tasks = json.loads(raw)
    except json.JSONDecodeError:
        tasks = {}

    if task not in tasks:
        print(f"✅ Aucune tâche '{task}' active — pas de contrainte de budget.")
        return

    data = tasks[task]
    over_tokens = data["budget_tokens"] > 0 and data["tokens"] >= data["budget_tokens"]
    over_xpoz = data["budget_xpoz"] > 0 and data["xpoz"] >= data["budget_xpoz"]

    if over_tokens or over_xpoz:
        print(f"⛔ BUDGET DÉPASSÉ pour '{task}'")
        if over_tokens:
            print(f"   Tokens : {data['tokens']} >= {data['budget_tokens']}")
        if over_xpoz:
            print(f"   Xpoz   : {data['xpoz']} >= {data['budget_xpoz']}")
        print("→ Action recommandée : arrêter ou fermer avec 'close' et réévaluer")
    else:
        remaining_t = data["budget_tokens"] - data["tokens"] if data["budget_tokens"] > 0 else "∞"
        remaining_x = data["budget_xpoz"] - data["xpoz"] if data["budget_xpoz"] > 0 else "∞"
        print(f"✅ Budget OK pour '{task}'")
        print(f"   Restant : {remaining_t} tokens, {remaining_x} Xpoz")


def cmd_close(task: str):
    """Ferme une tâche et archive son coût final."""
    raw = _ws_get("cg_active_tasks", "{}")
    try:
        tasks = json.loads(raw)
    except json.JSONDecodeError:
        tasks = {}

    if task not in tasks:
        print(f"❌ Tâche '{task}' introuvable.")
        return

    data = tasks.pop(task)
    _ws_set("cg_active_tasks", json.dumps(tasks))

    _log_history(task, data["tokens"], data["xpoz"],
                 data["budget_tokens"], data["budget_xpoz"],
                 "closed", "Tâche terminée")
    print(f"✅ Tâche '{task}' fermée")
    print(f"   Coût final : {data['tokens']} tokens, {data['xpoz']} Xpoz")
    print(f"   Durée : {data.get('started_at', '?')} → {datetime.now().isoformat()}")


def cmd_history():
    """Affiche l'historique des coûts."""
    conn = _get_db()
    c = conn.cursor()
    c.execute("""SELECT task, tokens, xpoz, budget_tokens, budget_xpoz,
                        decision, note, created_at
                 FROM cost_history ORDER BY id DESC LIMIT 30""")
    rows = c.fetchall()
    conn.close()

    if not rows:
        print("📜 Historique vide.")
        return

    print("📜 Historique des coûts (30 dernières entrées) :\n")
    total_t = sum(r[1] for r in rows)
    total_x = sum(r[2] for r in rows)
    print(f"   Totaux cumulés : {total_t} tokens, {total_x} Xpoz\n")

    for r in rows:
        task, tokens, xpoz, b_t, b_x, decision, note, ts = r
        icon = {"init": "🟢", "ok": "🟢", "closed": "🔵", "budget_exceeded": "🔴"}.get(decision, "⚪")
        preview = note[:60] if note else ""
        print(f"  {icon} [{ts[:19]}] {task}: {tokens}t / {xpoz}x — {decision} {preview}")


def main():
    parser = argparse.ArgumentParser(description="Cost Governor Black Intelligence")
    sub = parser.add_subparsers(dest="command", required=True)

    # status
    sub.add_parser("status", help="Voir l'état courant")

    # init
    p_init = sub.add_parser("init", help="Initialiser une tâche avec budget")
    p_init.add_argument("task", help="Nom de la tâche")
    p_init.add_argument("--token-budget", type=int, default=0, help="Budget tokens max (0 = illimité)")
    p_init.add_argument("--xpoz-budget", type=int, default=0, help="Budget crédits Xpoz max (0 = illimité)")

    # track
    p_track = sub.add_parser("track", help="Ajouter des coûts à une tâche")
    p_track.add_argument("task", help="Nom de la tâche")
    p_track.add_argument("--tokens", type=int, default=0, help="Tokens ajoutés")
    p_track.add_argument("--xpoz", type=int, default=0, help="Crédits Xpoz ajoutés")

    # check
    p_check = sub.add_parser("check", help="Vérifier le budget d'une tâche")
    p_check.add_argument("task", help="Nom de la tâche")

    # close
    p_close = sub.add_parser("close", help="Fermer une tâche")
    p_close.add_argument("task", help="Nom de la tâche")

    # history
    sub.add_parser("history", help="Voir l'historique des coûts")

    args = parser.parse_args()
    cmds = {
        "status": lambda: cmd_status(),
        "init": lambda: cmd_init(args.task, args.token_budget, args.xpoz_budget),
        "track": lambda: cmd_track(args.task, args.tokens, args.xpoz),
        "check": lambda: cmd_check(args.task),
        "close": lambda: cmd_close(args.task),
        "history": lambda: cmd_history(),
    }
    cmds[args.command]()


if __name__ == "__main__":
    main()
