#!/usr/bin/env bash
# auto_update.sh — Vérifie les mises à jour GitHub et redémarre Santana si nécessaire
# Utilisé par cron pour le déploiement continu

set -e
cd "$(dirname "$0")"

SELF_PID_FILE="/tmp/santana_update.pid"

# Éviter les exécutions concurrentes
if [ -f "$SELF_PID_FILE" ] && kill -0 $(cat "$SELF_PID_FILE") 2>/dev/null; then
    exit 0
fi
echo $$ > "$SELF_PID_FILE"
trap 'rm -f "$SELF_PID_FILE"' EXIT

# Vérifier si on a une remote configurée
if ! git remote -v 2>/dev/null | grep -q origin; then
    exit 0
fi

# Récupérer les changements sans merge (dry-run)
UPDATES=$(git fetch origin 2>&1)
BEHIND=$(git rev-list HEAD..origin/main --count 2>/dev/null || echo 0)

if [ "$BEHIND" -gt 0 ]; then
    echo "[AUTO_UPDATE] $(date) — $BEHIND commit(s) détectés, mise à jour..."
    
    # Pull
    git pull --ff-only origin main 2>&1 || {
        echo "[AUTO_UPDATE] Échec du pull, tentative rebase..."
        git stash 2>/dev/null
        git pull --rebase origin main 2>&1
        git stash pop 2>/dev/null
    }
    
    # Redémarrer Santana via systemd (préserve le service, le watchdog, le bon venv)
    echo "[AUTO_UPDATE] $(date) — Redémarrage de Santana via systemd..."
    systemctl --user restart santana
    echo "[AUTO_UPDATE] Santana redémarré"
fi
