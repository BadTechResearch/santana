#!/usr/bin/env bash
NEW="/tmp/symbad_new.py"
REAL="$HOME/symbad/symbad.py"
BACKUP_DIR="$HOME/symbad/backups/pre-edit"

if [ ! -f "$NEW" ]; then
  echo "❌ $NEW absent. Place le nouveau code dedans d'abord."
  exit 1
fi

mkdir -p "$BACKUP_DIR"
cp "$REAL" "$BACKUP_DIR/symbad.py.$(date +%Y%m%d-%H%M%S)"
echo "✅ Backup"

if python3 -m py_compile "$NEW"; then
  echo "✅ Syntaxe OK"
else
  echo "❌ ERREUR SYNTAXE — original non modifié"
  exit 1
fi

cp "$NEW" "$REAL"
sudo systemctl restart symbad
sleep 3

if sudo systemctl is-active --quiet symbad; then
  echo "✅ Hermès actif"
else
  echo "❌ Hermès FAILED — rollback"
  cp "$(ls -1t $BACKUP_DIR | head -1)" "$REAL"
  sudo systemctl restart symbad
  exit 1
fi

if curl -s http://localhost:5000/health | grep -q '"status":"ok"'; then
  echo "✅ API Flask répond — déploiement réussi"
else
  echo "❌ API Flask muette — rollback"
  cp "$(ls -1t $BACKUP_DIR | head -1)" "$REAL"
  sudo systemctl restart symbad
  exit 1
fi
