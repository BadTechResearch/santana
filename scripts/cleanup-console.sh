#!/bin/bash
# Nettoyage du service systemd console
# Exécuter : bash ~/hermes/cleanup-console.sh

echo "→ Arrêt du service..."
sudo systemctl stop hermes-console.service 2>/dev/null

echo "→ Désactivation du service..."
sudo systemctl disable hermes-console.service 2>/dev/null

echo "→ Suppression du fichier service..."
sudo rm -f /etc/systemd/system/hermes-console.service

echo "→ Rechargement systemd..."
sudo systemctl daemon-reload

echo "→ Vérification..."
sudo systemctl status hermes-console.service 2>&1 || echo "✅ Service supprimé avec succès"

echo ""
echo "✅ Terminé. La console n'existe plus nulle part."
