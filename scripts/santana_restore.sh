#!/bin/bash
# Santana Restore — restaure un snapshot complet du noyau
# Usage: bash santana_restore.sh            # Restaure le LATEST
#        bash santana_restore.sh 2026-07-04_120000_mon_patch  # Snapshot spécifique
#
# Vérifie l'intégrité du snapshot avant restauration.
# Ne touche pas à la base de données (memory.db).

set -euo pipefail

BASE_DIR="$HOME/santana"
SNAPSHOT_DIR="$BASE_DIR/backup/snapshots"
SNAPSHOT_NAME="${1:-latest}"

# Résoudre le chemin du snapshot
if [ "$SNAPSHOT_NAME" = "latest" ]; then
    if [ -f "$SNAPSHOT_DIR/.LATEST_PATH" ]; then
        SNAPSHOT=$(cat "$SNAPSHOT_DIR/.LATEST_PATH")
    else
        SNAPSHOT=$(ls -dt "$SNAPSHOT_DIR"/*/ 2>/dev/null | head -1)
        SNAPSHOT="${SNAPSHOT%/}"
    fi
else
    SNAPSHOT="$SNAPSHOT_DIR/${SNAPSHOT_NAME}"
fi

echo "═══════════════════════════════════════"
echo "  SANTANA RESTORE"
echo "═══════════════════════════════════════"

# Vérifier que le snapshot existe
if [ ! -d "$SNAPSHOT" ]; then
    echo "❌ Snapshot introuvable : $SNAPSHOT"
    echo ""
    echo "Snapshots disponibles :"
    ls -d "$SNAPSHOT_DIR"/*/ 2>/dev/null | while read s; do
        basename "$s"
    done
    exit 1
fi

# Afficher les metadata du snapshot
echo "Snapshot : $(basename $SNAPSHOT)"
if [ -f "$SNAPSHOT/META" ]; then
    cat "$SNAPSHOT/META"
fi
echo ""

# Vérifier l'intégrité
echo "--- Vérification intégrité ---"
CRITICAL_FILES=("core/react_loop.py" "santana.py")
MISSING=0
for file in "${CRITICAL_FILES[@]}"; do
    if [ -f "$SNAPSHOT/$file" ]; then
        echo "✅ $file ($(wc -c < "$SNAPSHOT/$file") octets)"
    else
        echo "❌ CRITIQUE : $file manquant"
        ((MISSING++))
    fi
done

if [ "$MISSING" -gt 0 ]; then
    echo "❌ Snapshot corrompu — $MISSING fichier(s) critique(s) manquant(s)"
    exit 1
fi

# Confirmation
echo ""
echo "⚠️  Cette action VA remplacer les fichiers actuels de Santana."
echo "   Les fichiers suivants seront restaurés :"
find "$SNAPSHOT" -type f ! -name 'META' ! -name 'GIT_*' ! -name '.LATEST_PATH' | \
    sed "s|$SNAPSHOT/||" | sort

echo ""
echo "   La base de données (memory.db) n'est PAS touchée."
echo ""
echo "Pour confirmer : bash scripts/santana_restore.sh --force $(basename $SNAPSHOT)"
echo ""

# Mode force
if [ "${1:-}" = "--force" ] || [ "${2:-}" = "--force" ]; then
    SNAPSHOT_NAME="${2:-$SNAPSHOT_NAME}"
    if [ "$1" = "--force" ]; then
        SNAPSHOT="$SNAPSHOT_DIR/${2:-latest}"
    fi
    
    echo "--- Restauration en cours ---"
    cd "$BASE_DIR"
    
    # Backup de l'état actuel avant restauration
    CURRENT_BACKUP="$SNAPSHOT_DIR/_before_restore_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$CURRENT_BACKUP/core" "$CURRENT_BACKUP/agent" "$CURRENT_BACKUP/tools"
    for f in santana.py core/react_loop.py core/provider.py; do
        if [ -f "$BASE_DIR/$f" ]; then
            cp "$BASE_DIR/$f" "$CURRENT_BACKUP/$f"
        fi
    done
    echo "📦 État actuel backupé dans : $(basename $CURRENT_BACKUP)"
    
    # Copie des fichiers restaurés
    RESTORED=0
    for filepath in $(find "$SNAPSHOT" -type f ! -name 'META' ! -name 'GIT_*' -path '*/core/*' -o \
                      -type f ! -name 'META' ! -name 'GIT_*' -name 'santana.py' -o \
                      -type f ! -name 'META' ! -name 'GIT_*' -path '*/agent/*' -o \
                      -type f ! -name 'META' ! -name 'GIT_*' -path '*/tools/*' -o \
                      -type f ! -name 'META' ! -name 'GIT_*' -path '*/memory/*' -o \
                      -type f ! -name 'META' ! -name 'GIT_*' -name 'metrics.py' | sed "s|$SNAPSHOT/||"); do
        cp "$SNAPSHOT/$filepath" "$BASE_DIR/$filepath"
        echo "  → restauré: $filepath"
        ((RESTORED++))
    done
    
    echo ""
    echo "✅ $RESTORED fichiers restaurés depuis $(basename $SNAPSHOT)"
    echo ""
    echo "Prochaine étape :"
    echo "  1. Vérifier : bash scripts/santana_validate.sh"
    echo "  2. Redémarrer : systemctl --user restart santana.service"
    echo "  3. Vérifier : journalctl --user -u santana.service -n 20 --no-pager"
fi
