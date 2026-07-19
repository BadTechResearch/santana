#!/usr/bin/env bash
# santana_ci_cron.sh — CI Santana via crontab système
# Exécute pytest et notifie Telegram en cas d'échec
# Silencieux si tout passe
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/venv_new/bin/python3"
TEST_FILES=("tests/test_system_integrity.py" "tests/test_100_performances.py")
TOKEN=$(grep -m1 "^TELEGRAM_TOKEN=" ".env" 2>/dev/null | cut -d= -f2-)
CHAT=$(grep -m1 "^CHAT_ID=" ".env" 2>/dev/null | cut -d= -f2-)

notify_telegram() {
    [ -z "$TOKEN" ] || [ -z "$CHAT" ] && return
    curl -s -m 10 "https://api.telegram.org/bot${TOKEN}/sendMessage" \
        -d "chat_id=${CHAT}" --data-urlencode "text=$1" > /dev/null
}

# ── Run tests ──
OUTPUT=$($VENV -m pytest "${TEST_FILES[@]}" -v --tb=line 2>&1)
EXIT_CODE=$?

# ── Build summary ──
PASS=$(echo "$OUTPUT" | grep -c "PASSED" || true)
FAIL=$(echo "$OUTPUT" | grep -c "FAILED" || true)
SKIP=$(echo "$OUTPUT" | grep -c "SKIPPED" || true)

TIMESTAMP=$(date '+%Y-%m-%d %H:%M')

if [ $EXIT_CODE -eq 0 ]; then
    # Tout passe — silencieux
    exit 0
fi

# ── Échec — envoyer résumé sur Telegram ──
FAILED_TESTS=$(echo "$OUTPUT" | grep "FAILED" | sed 's/^/• /' | head -10)

notify_telegram "🔴 Santana CI — $TIMESTAMP
⚠️ $FAIL échec(s) sur $((PASS + FAIL)) tests

$FAILED_TESTS

📊 $PASS ✅ | $FAIL ❌ | $SKIP ⏭️"

exit $EXIT_CODE
