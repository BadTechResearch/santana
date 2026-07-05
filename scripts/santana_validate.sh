#!/bin/bash
# Santana Validation Gate — vérifie l'intégrité du noyau avant/après modification
# Retourne 0 si tout OK, non-zero avec détails si échec
#
# Usage: bash santana_validate.sh [--verbose] [--mode=pre|post]
#   --verbose : affiche tous les détails
#   --mode=pre : mode pré-modification (seulement L0)
#   --mode=post : mode post-modification (tous les niveaux)

set -euo pipefail

BASE_DIR="$HOME/santana"
cd "$BASE_DIR"

# Parse arguments
VERBOSE=false
MODE="full"
for arg in "$@"; do
    case "$arg" in
        --verbose) VERBOSE=true ;;
        --mode=pre) MODE="pre" ;;
        --mode=post) MODE="post" ;;
    esac
done

FAILURES=0
WARNINGS=0

echo "═══════════════════════════════════════════"
echo "  SANTANA VALIDATION GATE"
echo "  Mode : $MODE"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════"

# ─── L0 : Compilation Python ───
echo ""
echo "── [L0] Compilation Python ──"
python3 << 'PYEOF' 2>&1 && COMPILE_OK=true || COMPILE_OK=false
import py_compile, sys, os
BASE = os.path.expanduser("~/santana")
EXCLUDE = {'venv_new', '.venv', '__pycache__', '.git', 'backup', '__pycache__'}
errors = []
count = 0
for root, dirs, files in os.walk(BASE):
    dirs[:] = [d for d in dirs if d not in EXCLUDE]
    for f in files:
        if not f.endswith('.py'): continue
        path = os.path.join(root, f)
        try:
            py_compile.compile(path, doraise=True)
            count += 1
        except py_compile.PyCompileError as e:
            errors.append((path, str(e)))
if errors:
    for p, e in errors:
        print(f'  ❌ {p}: {e}')
    sys.exit(1)
else:
    print(f'  ✅ {count} fichiers .py compilent')
PYEOF

$COMPILE_OK || ((FAILURES++))

# ─── L0 bis : Syntaxe AST ───
echo ""
echo "── [L0] Syntaxe AST — vérification complète ──"
python3 << 'PYEOF' 2>&1 && AST_OK=true || AST_OK=false
import ast, sys, os
BASE = os.path.expanduser("~/santana")
EXCLUDE = {'venv_new', '.venv', '__pycache__', '.git', 'backup'}
errors = []
count = 0
for root, dirs, files in os.walk(BASE):
    dirs[:] = [d for d in dirs if d not in EXCLUDE]
    for f in files:
        if not f.endswith('.py'): continue
        path = os.path.join(root, f)
        count += 1
        try:
            with open(path) as fh:
                ast.parse(fh.read())
        except SyntaxError as e:
            errors.append((path, str(e)))
if errors:
    for p, e in errors:
        print(f'  ❌ {p}: {e}')
    sys.exit(1)
else:
    print(f'  ✅ {count} fichiers .py syntaxiquement valides')
PYEOF

$AST_OK || ((FAILURES++))

# Si mode pre, on s'arrête là
if [ "$MODE" = "pre" ]; then
    echo ""
    echo "═══════════════════════════════════════════"
    echo "  BILAN (PRE-MODIFICATION) : $FAILURES échec(s)"
    echo "═══════════════════════════════════════════"
    exit $FAILURES
fi

# ─── L1 : Tests unitaires ciblés ───
echo ""
echo "── [L1] Tests unitaires (modules noyau) ──"
for mod in core/react_loop core/provider agent/orchestrator agent/self; do
    mod_name=$(basename $mod)
    TEST_FILE="tests/test_${mod_name}.py"
    if [ -f "$TEST_FILE" ]; then
        OUTPUT=$(python3 -m pytest "$TEST_FILE" -q --tb=line 2>&1) || true
        LAST=$(echo "$OUTPUT" | grep -E '(passed|failed|error)' | tail -1)
        if echo "$LAST" | grep -q "failed"; then
            echo "  ❌ $mod_name : $LAST"
            ((FAILURES++))
        else
            echo "  ✅ $mod_name : $LAST"
        fi
        $VERBOSE && echo "$OUTPUT" | grep -v "^$\|^===" | head -20
    else
        echo "  ⚠️  Pas de test pour $mod_name (normal si nouveau module)"
    fi
done

# ─── L1 bis : Tests des outils modifiés ───
if [ -f "tests/test_tools.py" ]; then
    echo ""
    echo "── [L1] Tests outils ──"
    OUTPUT=$(python3 -m pytest tests/test_tools.py -q --tb=line 2>&1) || true
    LAST=$(echo "$OUTPUT" | grep -E '(passed|failed|error)' | tail -1)
    if echo "$LAST" | grep -q "failed"; then
        echo "  ❌ tools : $LAST"
        ((FAILURES++))
    else
        echo "  ✅ tools : $LAST"
    fi
fi

# ─── L2 : Tests d'intégration ───
echo ""
echo "── [L2] Tests d'intégration (pytest -q sans 100-level) ──"
# Exclure les tests 100-level qui peuvent timeout (appels API réels)
OUTPUT=$(python3 -m pytest tests/ -q --tb=short --ignore=tests/test_100_securite.py --ignore=tests/test_100_securite_redteam.py -x 2>&1) || true
LAST=$(echo "$OUTPUT" | grep -E '(passed|failed|error)' | tail -1)

if echo "$LAST" | grep -q "failed"; then
    echo "  ❌ Intégration : $LAST"
    ((FAILURES++))
    echo ""
    echo "  Détail des échecs :"
    python3 -m pytest tests/ -q --tb=line --ignore=tests/test_100_securite.py --ignore=tests/test_100_securite_redteam.py 2>&1 | grep "FAILED" | head -5
else
    echo "  ✅ Intégration : $LAST"
fi

# ─── L3 : Import noyau ───
echo ""
echo "── [L3] Import noyau + smoke test ──"
python3 -c "
import sys
sys.path.insert(0, '.')
from core.react_loop import react_loop
from core.provider import PROVIDER_CHAIN
from agent.orchestrator import build_system_prompt
print('✅ Tous les imports noyau OK')
print(f'   PROVIDER_CHAIN: {len(PROVIDER_CHAIN)} providers')
" 2>&1 && IMPORT_OK=true || IMPORT_OK=false

$IMPORT_OK || ((FAILURES++))

# ─── Résumé ───
echo ""
echo "═══════════════════════════════════════════"
if [ "$FAILURES" -eq 0 ]; then
    echo "  ✅ VALIDATION PASSÉE — 0 échec, $WARNINGS avertissement(s)"
else
    echo "  ❌ VALIDATION ÉCHOUÉE — $FAILURES échec(s)"
fi
echo "═══════════════════════════════════════════"

exit $FAILURES
