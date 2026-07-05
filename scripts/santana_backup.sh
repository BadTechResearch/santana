#!/bin/bash
# Santana Auto-Backup — crée un snapshot complet du noyau avant modification
# Usage: bash santana_backup.sh [nom_patch]
# 
# Crée un point de restauration dans backup/snapshots/
# Vérifie l'intégrité après copie
#
# Installation:
#   chmod +x ~/santana/scripts/santana_backup.sh
#   mkdir -p ~/santana/backup/snapshots

set -euo pipefail

BASE_DIR="$HOME/santana"
SNAPSHOT_DIR="$BASE_DIR/backup/snapshots"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
PATCH_NAME="${1:-auto}"
SNAPSHOT="$SNAPSHOT_DIR/${TIMESTAMP}_${PATCH_NAME}"

echo "═══════════════════════════════════════"
echo "  SANTANA BACKUP"
echo "  Timestamp : $TIMESTAMP"
echo "  Patch     : $PATCH_NAME"
echo "═══════════════════════════════════════"

# Créer le répertoire du snapshot
mkdir -p "$SNAPSHOT"
mkdir -p "$SNAPSHOT/core" "$SNAPSHOT/agent" "$SNAPSHOT/tools" "$SNAPSHOT/memory"

# 1. Git stash (sauvegarde des modifs non commit)
cd "$BASE_DIR"
STASH_CREATED=false
if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    git stash push -m "auto-backup-$TIMESTAMP" 2>/dev/null || true
    STASH_CREATED=true
    echo "[1/5] Modifications non commit stashées"
else
    echo "[1/5] Aucune modification non commit"
fi

# 2. Backup des fichiers du noyau
echo "[2/5] Copie des fichiers noyau..."
for file in santana.py \
            core/react_loop.py core/provider.py core/db.py \
            core/delegate.py core/utils.py core/cache.py \
            agent/orchestrator.py agent/context.py agent/evaluator.py \
            agent/self.py agent/patterns.py agent/securite.py \
            agent/souverainete.py agent/tracabilite.py agent/orchestration.py \
            tools/cost_governor.py tools/telegram_stream.py \
            memory/memory.py metrics.py; do
    if [ -f "$BASE_DIR/$file" ]; then
        cp "$BASE_DIR/$file" "$SNAPSHOT/$file"
    fi
done

# 3. Git metadata
echo "[3/5] Enregistrement metadata git..."
git rev-parse HEAD > "$SNAPSHOT/GIT_HEAD" 2>/dev/null
git log --oneline -10 > "$SNAPSHOT/GIT_LOG" 2>/dev/null
git stash list > "$SNAPSHOT/GIT_STASH" 2>/dev/null || true

# 4. Metadata du snapshot
echo "[4/5] Écriture metadata..."
cat > "$SNAPSHOT/META" << EOF
TIMESTAMP=$TIMESTAMP
PATCH=$PATCH_NAME
USER=$(whoami)
HOST=$(hostname)
STASH_PENDING=$STASH_CREATED
EOF

echo "$SNAPSHOT" > "$SNAPSHOT_DIR/.LATEST_PATH"

# 5. Vérification d'intégrité
echo "[5/5] Vérification intégrité..."
ERRORS=0
for file in core/react_loop.py santana.py; do
    if [ -f "$SNAPSHOT/$file" ]; then
        SIZE=$(wc -c < "$SNAPSHOT/$file")
        if [ "$SIZE" -gt 0 ]; then
            echo "  ✅ $file ($SIZE octets)"
        else
            echo "  ❌ $file : VIDE"
            ((ERRORS++))
        fi
    else
        echo "  ⚠️  $file : absent (normal si fichier supprimé)"
    fi
done

if [ "$ERRORS" -eq 0 ]; then
    echo ""
    echo "✅ BACKUP RÉUSSI : $SNAPSHOT"
    du -sh "$SNAPSHOT"
    echo ""
    echo "Pour restaurer : bash scripts/santana_restore.sh ${TIMESTAMP}_${PATCH_NAME}"
else
    echo ""
    echo "❌ BACKUP INCOMPLET — $ERRORS erreur(s)"
    exit 1
fi
