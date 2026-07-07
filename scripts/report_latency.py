#!/usr/bin/env python3
"""report_latency.py — Rapport de performance depuis metrics.db.

Usage :
    python scripts/report_latency.py          # Résumé des dernières 24h
    python scripts/report_latency.py --hours 72  # Fenêtre personnalisée
    python scripts/report_latency.py --csv       # Export CSV brut

Analyse les métriques de latence collectées par Phase 4 :
  - TTFT moyen/min/max par type de message
  - Latence totale moyenne/min/max
  - Compteur d'outils et de flood 429
"""

import os, sys, json, sqlite3
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METRICS_DB = os.path.join(BASE_DIR, "metrics.db")

HOURS = 24
EXPORT_CSV = False

for arg in sys.argv[1:]:
    if arg.startswith("--hours="):
        HOURS = int(arg.split("=", 1)[1])
    elif arg == "--csv":
        EXPORT_CSV = True
    elif arg.startswith("--hours"):
        idx = sys.argv.index(arg) + 1
        if idx < len(sys.argv):
            HOURS = int(sys.argv[idx])

NOW = datetime.now()
SINCE = NOW - timedelta(hours=HOURS)


def fmt(ms: int) -> str:
    if ms is None:
        return "N/A"
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms/1000:.1f}s"


def main():
    if not os.path.exists(METRICS_DB):
        print(f"❌ Base introuvable : {METRICS_DB}")
        print("   Santana n'a encore enregistré aucune métrique de latence.")
        sys.exit(1)

    conn = sqlite3.connect(METRICS_DB)
    conn.row_factory = sqlite3.Row

    # Vérifier si la table existe
    tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "message_latency" not in tables:
        print("❌ Table 'message_latency' inexistante.")
        print("   La Phase 4 a été déployée mais aucun message n'a encore été traité.")
        sys.exit(1)

    since_iso = SINCE.strftime("%Y-%m-%d %H:%M:%S")

    # ── 1. Résumé global ──────────────────────────────────────────
    row = conn.execute("""
        SELECT
            COUNT(*) as total,
            COALESCE(AVG(ttft_ms), 0) as avg_ttft,
            COALESCE(MAX(ttft_ms), 0) as max_ttft,
            COALESCE(MIN(ttft_ms), 0) as min_ttft,
            COALESCE(AVG(total_ms), 0) as avg_total,
            COALESCE(MAX(total_ms), 0) as max_total,
            COALESCE(MIN(total_ms), 0) as min_total,
            COALESCE(AVG(tool_count), 0) as avg_tools,
            COALESCE(AVG(flood_429_count), 0) as avg_429,
            SUM(flood_429_count) as total_429
        FROM message_latency
        WHERE timestamp >= ?
    """, (since_iso,)).fetchone()

    total = row["total"]

    if total == 0:
        print(f"📊 Aucune métrique enregistrée depuis {since_iso}")
        conn.close()
        return

    print(f"{'─' * 50}")
    print(f"📊 RAPPORT DE LATENCE — {SINCE.strftime('%d/%m %H:%M')} → {NOW.strftime('%d/%m %H:%M')}")
    print(f"{'─' * 50}")
    print(f"Messages traités       : {total}")
    print(f"TTFT moyen             : {fmt(int(row['avg_ttft']))}")
    print(f"TTFT min               : {fmt(int(row['min_ttft']))}")
    print(f"TTFT max               : {fmt(int(row['max_ttft']))}")
    print(f"Latence totale moyenne : {fmt(int(row['avg_total']))}")
    print(f"Latence totale min     : {fmt(int(row['min_total']))}")
    print(f"Latence totale max     : {fmt(int(row['max_total']))}")
    print(f"Outils moyens/tour     : {row['avg_tools']:.1f}")
    print(f"Flood 429 total        : {int(row['total_429'])}")
    print()

    # ── 2. Par type de message ────────────────────────────────────
    rows = conn.execute("""
        SELECT
            msg_type,
            COUNT(*) as total,
            AVG(ttft_ms) as avg_ttft,
            MAX(ttft_ms) as max_ttft,
            MIN(ttft_ms) as min_ttft,
            AVG(total_ms) as avg_total,
            MAX(total_ms) as max_total,
            AVG(tool_count) as avg_tools,
            SUM(flood_429_count) as total_429
        FROM message_latency
        WHERE timestamp >= ?
        GROUP BY msg_type
        ORDER BY total DESC
    """, (since_iso,)).fetchall()

    print(f"{'─' * 50}")
    print("PAR TYPE DE MESSAGE :")
    print(f"{'─' * 50}")
    print(f"{'Type':<14} {'#':>3} {'TTFT⌀':>8} {'TTFT⇧':>8} {'TTFT⇩':>8} {'Tot⌀':>8} {'Tot⇧':>8} {'Outils⌀':>8} {'429':>5}")
    print(f"{'─' * 80}")
    for r in rows:
        print(
            f"{r['msg_type']:<14} {r['total']:>3} "
            f"{fmt(int(r['avg_ttft'])):>8} {fmt(int(r['max_ttft'])):>8} {fmt(int(r['min_ttft'])):>8} "
            f"{fmt(int(r['avg_total'])):>8} {fmt(int(r['max_total'])):>8} "
            f"{r['avg_tools']:>8.1f} {int(r['total_429']):>5}"
        )
    print()

    # ── 3. Derniers messages lents ────────────────────────────────
    slow = conn.execute("""
        SELECT timestamp, msg_type, ttft_ms, total_ms, tool_count
        FROM message_latency
        WHERE timestamp >= ?
        ORDER BY total_ms DESC
        LIMIT 5
    """, (since_iso,)).fetchall()

    print(f"{'─' * 50}")
    print("TOP 5 MESSAGES LES PLUS LENTS :")
    print(f"{'─' * 50}")
    for r in slow:
        print(f"  {r['timestamp']} | {r['msg_type']:<10} | "
              f"TTFT {fmt(r['ttft_ms']):>8} | Total {fmt(r['total_ms']):>8} | "
              f"{r['tool_count']} outil(s)")

    # ── 4. Export CSV si demandé ──────────────────────────────────
    if EXPORT_CSV:
        csv_path = os.path.join(BASE_DIR, f"latency_report_{NOW.strftime('%Y%m%d_%H%M')}.csv")
        rows_csv = conn.execute("""
            SELECT timestamp, msg_type, ttft_ms, total_ms, tool_count,
                   flood_429_count, token_count, provider, user_msg_len
            FROM message_latency
            WHERE timestamp >= ?
            ORDER BY timestamp
        """, (since_iso,)).fetchall()
        with open(csv_path, "w") as f:
            f.write("timestamp,msg_type,ttft_ms,total_ms,tool_count,flood_429,token_count,provider,msg_len\n")
            for r in rows_csv:
                f.write(f"{r['timestamp']},{r['msg_type']},{r['ttft_ms']},{r['total_ms']},"
                        f"{r['tool_count']},{r['flood_429_count']},{r['token_count']},"
                        f"{r['provider']},{r['user_msg_len']}\n")
        print(f"\n📄 CSV exporté : {csv_path}")

    conn.close()


if __name__ == "__main__":
    main()
