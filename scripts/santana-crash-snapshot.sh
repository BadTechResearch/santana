#!/bin/bash
# santana-crash-snapshot.sh — Exécuté par ExecStopPost après un crash
# Sauvegarde l'état pour investigation et active le mode dégradé si nécessaire.

BASE="/home/user/hermes"
SNAPSHOT_DIR="$BASE/.crash_snapshots"
mkdir -p "$SNAPSHOT_DIR"

TIMESTAMP=$(date +"%Y%m%d-%H%M%S")

# 1. Sauvegarder la base mémoire
if [ -f "$BASE/memory.db" ]; then
    cp "$BASE/memory.db" "$SNAPSHOT_DIR/memory_$TIMESTAMP.db"
    chmod 600 "$SNAPSHOT_DIR/memory_$TIMESTAMP.db"
    echo "[SNAPSHOT] memory.db sauvegardé"
fi

# 2. Sauvegarder les logs récents
if [ -f "$BASE/hermes.log" ]; then
    tail -200 "$BASE/hermes.log" > "$SNAPSHOT_DIR/log_$TIMESTAMP.txt"
    chmod 600 "$SNAPSHOT_DIR/log_$TIMESTAMP.txt"
    echo "[SNAPSHOT] logs sauvegardés"
fi

# 3. Journal systemd
journalctl -u hermes.service -n 50 --no-pager > "$SNAPSHOT_DIR/journal_$TIMESTAMP.txt" 2>/dev/null || true
chmod 600 "$SNAPSHOT_DIR/journal_$TIMESTAMP.txt" 2>/dev/null || true

# 4. Nettoyer les vieux snapshots (garder 5 .db + 10 .txt récents)
ls -t "$SNAPSHOT_DIR"/*.db 2>/dev/null | tail -n +6 | xargs -r rm
ls -t "$SNAPSHOT_DIR"/*.txt 2>/dev/null | tail -n +11 | xargs -r rm

# 5. Compter les crashs dans la dernière heure
LAST_HOUR=$(date -d '1 hour ago' +"%Y%m%d-%H%M%S")
COUNT=0
for f in "$SNAPSHOT_DIR"/memory_*.db; do
    fname=$(basename "$f")
    fdate=${fname#memory_}
    fdate=${fdate%.db}
    if [[ "$fdate" > "$LAST_HOUR" ]]; then
        COUNT=$((COUNT + 1))
    fi
done

# 6. Activer le mode dégradé si ≥ 3 crashs dans la dernière heure
FLAG_FILE="$BASE/.crash_flag"
if [ "$COUNT" -ge 3 ]; then
    echo "{\"active\": true, \"count\": $COUNT, \"since\": \"$(date -Iseconds)\"}" > "$FLAG_FILE"
    echo "[SNAPSHOT] ⚠️ Mode dégradé activé ($COUNT crashs dans l'heure)"
else
    rm -f "$FLAG_FILE" 2>/dev/null
fi

exit 0
