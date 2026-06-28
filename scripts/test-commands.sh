#!/bin/bash
# test-commands.sh — Vérifie que Santana répond aux commandes Telegram
# Usage: ./test-commands.sh
# Exit 0 si tout OK, non-zero si échec
#
# CONFIG : édite TOKEN et CHAT_ID avec les valeurs de production
# ATTENTION : ce script envoie de VRAIS messages Telegram.

TOKEN=$(grep TELEGRAM_TOKEN= ~/hermes/.env 2>/dev/null | cut -d= -f2-)
CHAT_ID=$(grep CHAT_ID= ~/hermes/.env 2>/dev/null | cut -d= -f2-)

if [ -z "$TOKEN" ] || [ -z "$CHAT_ID" ]; then
    echo "❌ TELEGRAM_TOKEN ou CHAT_ID manquant dans .env"
    exit 1
fi

API="https://api.telegram.org/bot${TOKEN}"

# Commandes obligatoires
COMMANDS=(
    "/start"
    "/help"
    "/status"
    "/statut"
    "/steward"
    "/livres"
    "/flux"
    "/registre"
)

PASS=0
FAIL=0
FAILED_CMDS=""

for cmd in "${COMMANDS[@]}"; do
    echo -n "  ➜ $cmd ... "
    # Envoie la commande et attend la réponse (timeout 8s)
    SENT=$(curl -s -m 5 "$API/sendMessage" \
        -d chat_id="$CHAT_ID" \
        -d text="$cmd" 2>&1)

    if echo "$SENT" | grep -q '"ok":true'; then
        echo "✅"
        PASS=$((PASS + 1))
    else
        echo "❌ $(echo "$SENT" | grep -oP '"description":"[^"]*"' | head -1)"
        FAIL=$((FAIL + 1))
        FAILED_CMDS="$FAILED_CMDS $cmd"
    fi

    # Pause pour éviter rate limiting
    sleep 1
done

echo ""
echo "═══════════════════════════════════"
echo "Résultats : $PASS OK / $((PASS + FAIL)) total"
if [ "$FAIL" -gt 0 ]; then
    echo "❌ Échecs :$FAILED_CMDS"
    exit 1
fi
echo "✅ Toutes les commandes répondent"
exit 0
