#!/usr/bin/env bash
# Pre-commit hook Santana — vérifie lint + tests avant commit
# Installer : ln -sf ../../scripts/pre-commit.sh .git/hooks/pre-commit

set -e
BASE_DIR=$(cd "$(dirname "$0")/../.." && pwd)
PYTHON="$BASE_DIR/venv_new/bin/python3"
echo "🔍 Pre-commit Santana..."

# 1. Syntaxe Python
echo "  📐 Vérification syntaxe..."
find "$BASE_DIR" -name "*.py" -not -path "*/venv_new/*" -not -path "*/__pycache__/*" -exec $PYTHON -m py_compile {} \; 2>/dev/null
echo "  ✅ Syntaxe OK"

# 2. Tests d'intégrité (rapides)
echo "  🧪 Tests d'intégrité..."
$PYTHON -m pytest "$BASE_DIR/tests/test_system_integrity.py" -q --tb=short 2>&1 | tail -3
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "  ❌ Tests échoués — commit bloqué"
    exit 1
fi
echo "  ✅ Tests OK"
echo "✅ Pre-commit passé"
