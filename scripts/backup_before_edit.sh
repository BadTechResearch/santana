#!/usr/bin/env bash
# backup_before_edit.sh — Auto-backup avant modification de fichiers critiques
# Usage: ./scripts/backup_before_edit.sh <file1> [file2 ...]
# Crée un commit automatique de l'état actuel avant modification

set -e

CRITICAL_FILES=(
    "agent/orchestrator.py"
    "soul/RULES.md"
    "soul/SOUL.md"
    "soul/STYLE.md"
    "soul/USER.md"
    "core/react_loop.py"
    "core/db.py"
    "deepseek_client.py"
)

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

# Vérifier que git est disponible
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "❌ Pas un dépôt git"
    exit 1
fi

COMMITTED=0

for file in "$@"; do
    # Vérifier si le fichier existe
    if [ ! -f "$file" ]; then
        echo "⚠️  $file n'existe pas, ignoré"
        continue
    fi

    # Vérifier si le fichier est dans la liste critique
    is_critical=0
    for critical in "${CRITICAL_FILES[@]}"; do
        if [[ "$file" == "$critical" ]]; then
            is_critical=1
            break
        fi
    done

    if [[ $is_critical -eq 1 ]]; then
        echo "📦 Backup de $file..."
        TIMESTAMP=$(date +%Y-%m-%dT%H:%M:%S)
        if git add "$file" 2>/dev/null; then
            if git commit -m "[AUTO-BACKUP] avant modification de $file — $TIMESTAMP" 2>/dev/null; then
                echo "  ✅ Backup commité : $file"
                COMMITTED=1
            else
                echo "  ℹ️  $file — pas de changement à backup"
            fi
        fi
    else
        echo "ℹ️  $file n'est pas dans la liste critique. Utilisation quand même ? (y/N)"
        read -r answer
        if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
            TIMESTAMP=$(date +%Y-%m-%dT%H:%M:%S)
            git add "$file" && git commit -m "[AUTO-BACKUP] avant modification de $file — $TIMESTAMP"
            COMMITTED=1
        fi
    fi
done

if [[ $COMMITTED -eq 1 ]]; then
    echo ""
    echo "📤 Push automatique..."
    git push origin main 2>/dev/null || echo "  ⚠️  Push échoué (pas de remote ou réseau)"
    echo ""
    echo "✅ Backup terminé. Tu peux modifier les fichiers en toute sécurité."
fi
