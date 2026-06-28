#!/usr/bin/env bash
# benchmark_guard.sh — Vérifie que Santana passe le benchmark avant de valider des changements
# Usage: ./scripts/benchmark_guard.sh [--quick] [--file <path>]
# Retourne 0 si OK, 1 si échec

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

BENCHMARK_RUNNER="_benchmark_santana_auto.py"
MODE="quick"  # quick = 8 tests, full = 28 tests
CHECK_FILE=""

# Parsing des arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --quick) MODE="quick"; shift ;;
        --full)  MODE="full"; shift ;;
        --file)  CHECK_FILE="$2"; shift 2 ;;
        *)       echo "Usage: $0 [--quick|--full] [--file <path>]"; exit 1 ;;
    esac
done

# Vérifier si les fichiers critiques sont modifiés
CRITICAL_FILES=(
    "agent/orchestrator.py"
    "soul/RULES.md"
    "soul/SOUL.md"
    "soul/STYLE.md"
    "core/react_loop.py"
    "deepseek_client.py"
)

IS_CRITICAL=0
if [ -n "$CHECK_FILE" ]; then
    for cf in "${CRITICAL_FILES[@]}"; do
        if [[ "$CHECK_FILE" == "$cf" ]]; then
            IS_CRITICAL=1
            break
        fi
    done
else
    # Vérifier si des fichiers critiques sont dans les staged files
    for cf in "${CRITICAL_FILES[@]}"; do
        if git diff --cached --name-only 2>/dev/null | grep -q "^$cf$"; then
            IS_CRITICAL=1
            break
        fi
    done
    # Aussi les unstaged changes
    if [ "$IS_CRITICAL" -eq 0 ]; then
        for cf in "${CRITICAL_FILES[@]}"; do
            if git diff --name-only 2>/dev/null | grep -q "^$cf$"; then
                IS_CRITICAL=1
                break
            fi
        done
    fi
fi

if [ "$IS_CRITICAL" -eq 0 ] && [ -z "$CHECK_FILE" ]; then
    echo "ℹ️  Aucun fichier critique modifié — benchmark ignoré"
    exit 0
fi

echo "🧪 Benchmark guard — vérification en cours..."
echo ""

# Vérifier que le runner existe
if [ ! -f "$BENCHMARK_RUNNER" ]; then
    echo "⚠️  Runner benchmark introuvable : $BENCHMARK_RUNNER"
    echo "   Le benchmark ne peut pas être vérifié automatiquement."
    exit 0  # Ne pas bloquer si le runner n'existe pas
fi

# Lancer le benchmark quick (8 tests, ~1 min)
echo "🔬 Lancement du benchmark mode $MODE..."
START_TIME=$(date +%s)

if python3 "$BENCHMARK_RUNNER" 2>&1; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo ""
    echo "✅ Benchmark passé en ${DURATION}s — OK pour commit"
    exit 0
else
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo ""
    echo "❌ Benchmark ÉCHOUÉ après ${DURATION}s"
    echo ""
    echo "   Des fichiers critiques ont été modifiés et le benchmark ne passe plus."
    echo "   Solutions :"
    echo "     1. Corriger les régressions détectées"
    echo "     2. Commit sans benchmark : git commit --no-verify"
    echo "     3. Voir les résultats dans benchmark_results/"
    exit 1
fi
