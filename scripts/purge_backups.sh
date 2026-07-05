#!/usr/bin/env bash
# Purge les vieux backups Santana — garde les KEEP plus récents de chaque type.
# Usage: bash scripts/purge_backups.sh
# À mettre en cron : 0 3 * * * bash ~/santana/scripts/purge_backups.sh

set -euo pipefail

BACKUP_DIR="$HOME/santana/_backups"
KEEP=10  # garde les 10 plus récents de chaque préfixe

if [ ! -d "$BACKUP_DIR" ]; then
    echo "[PURGE] Aucun dossier _backups, rien à purger"
    exit 0
fi

for prefix in metrics_ memory_; do
    count=$(ls -1 "$BACKUP_DIR"/${prefix}*.db 2>/dev/null | wc -l)
    if [ "$count" -le "$KEEP" ]; then
        echo "[PURGE] $prefix: $count fichiers (≤ $KEEP, rien à faire)"
        continue
    fi
    to_delete=$((count - KEEP))
    ls -t "$BACKUP_DIR"/${prefix}*.db | tail -n "$to_delete" | while read -r f; do
        rm -f -- "$f"
        echo "[PURGE] Supprimé: $(basename "$f")"
    done
    echo "[PURGE] $prefix: $to_delete fichiers supprimés (${KEEP} conservés)"
done

echo "[PURGE] Terminé"
