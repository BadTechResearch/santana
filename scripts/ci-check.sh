#!/usr/bin/env bash
# CI minimal Hermes — vérifie syntaxe + tests avant déploiement
# Usage: ./ci-check.sh
# Exit 0 si OK, non-zero si échec

set -e
PROJECT_DIR="$HOME/hermes"
cd "$PROJECT_DIR"

log() { echo "[CI] $*"; }
fail() { echo "[CI] ❌ $*"; exit 1; }

# 1. Compilation syntaxique de tous les .py
log "🔍 Vérification syntaxique..."
find . -name '*.py' \
  -not -path './__pycache__/*' \
  -not -path './*/__pycache__/*' \
  -print0 | while IFS= read -r -d '' f; do
  python3 -m py_compile "$f" 2>/dev/null || fail "Erreur syntaxe dans $f"
done
log "✅ Syntaxe OK sur tout le projet"

# 2. Pytest — modules rapides uniquement (exclut embeddings lents et memory_query)
log "🧪 Tests unitaires..."
python3 -m pytest tests/test_utils.py tests/test_memory.py tests/test_tools.py::TestExecuteTool tests/test_tools.py::TestSkillsTools tests/test_react_loop.py -q --tb=short 2>&1
echo ""
log "✅ Tests OK"

echo "[CI] ✅ Tout est vert — déploiement autorisé"
