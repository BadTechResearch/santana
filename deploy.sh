#!/usr/bin/env bash
# deploy.sh — Déploiement continu Santana
# Usage: ./deploy.sh [message]
#   ./deploy.sh              → commit auto avec message généré
#   ./deploy.sh "fix: bug X" → commit avec message personnalisé

set -e
cd "$(dirname "$0")"

BRANCH="main"
REMOTE="origin"
SANTANA_PID_FILE="/tmp/santana.pid"

echo "🚀 Déploiement Santana — $(date)"

# 1) Vérifier les changements
if [ -z "$(git status --porcelain)" ]; then
    echo "✅ Aucun changement à déployer."
    exit 0
fi

# 2) Git add + commit
git add -A
if [ -n "$1" ]; then
    git commit -m "$1"
else
    # Message automatique basé sur les fichiers modifiés
    FILES=$(git diff --cached --name-only | tr '\n' ' ')
    git commit -m "deploy: $(date '+%Y-%m-%d %H:%M') — ${FILES:0:80}..."
fi

# 3) Push
echo "📤 Push vers $REMOTE/$BRANCH..."
git push "$REMOTE" "$BRANCH" 2>&1 | tail -3

# 4) Pull (cas où on a aussi reçu des changements depuis le remote)
git pull --rebase "$REMOTE" "$BRANCH" 2>&1 | tail -3

# 5) Redémarrer Santana
echo "🔄 Redémarrage de Santana..."
pkill -f "python.*santana.py" 2>/dev/null || true
sleep 2

cd ~/santana
nohup ./venv/bin/python santana.py > santana.log 2>&1 &
echo $! > "$SANTANA_PID_FILE"
sleep 3

# Vérification
if kill -0 $(cat "$SANTANA_PID_FILE") 2>/dev/null; then
    echo "✅ Santana redémarré (PID $(cat "$SANTANA_PID_FILE"))"
else
    echo "❌ Échec du redémarrage"
    exit 1
fi

echo "🏁 Déploiement terminé"
