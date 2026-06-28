#!/usr/bin/env bash
# Santana Doctor — Vérification santé au démarrage et diagnostic
# Usage: ./santana-doctor.sh [--fix]

set -e

BASE_DIR="$HOME/santana"
VENV="$BASE_DIR/venv_new"
PYTHON="$VENV/bin/python3"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
pass=0; fail=0

check() {
    if [ $? -eq 0 ]; then
        echo -e "  ${GREEN}✅${NC} $1"
        pass=$((pass+1))
    else
        echo -e "  ${RED}❌${NC} $1"
        fail=$((fail+1))
    fi
}

echo "🔍 Santana Doctor — Diagnostic"
echo "================================"
echo ""

# 1. Process
echo "📋 Process:"
systemctl --user is-active santana >/dev/null 2>&1
check "Service systemd santana actif"

# 2. DB
echo "📦 Base de données:"
[ -f "$BASE_DIR/memory.db" ] && $PYTHON -c "import sqlite3; sqlite3.connect('$BASE_DIR/memory.db').execute('PRAGMA integrity_check').fetchone()" 2>/dev/null
check "Intégrité memory.db"

# 3. LLM
echo "🤖 LLM:"
$PYTHON -c "
from core.utils import load_env; load_env('$BASE_DIR/.env')
import os
d = os.getenv('DEEPSEEK_API_KEY','')
print('DeepSeek:', '✅' if d else '❌')
from core.provider import _init_providers, PROVIDER_CHAIN
_init_providers()
for p in PROVIDER_CHAIN:
    print(f'  {p[\"name\"]}: ✅ clé présente')
" 2>/dev/null

# 4. Outils
echo "🛠️ Outils:"
$PYTHON -c "
import sys; sys.path.insert(0,'$BASE_DIR')
from tools.tools import TOOLS
print(f'  {len(TOOLS)} outils chargés')
for t in TOOLS:
    print(f'    - {t[\"function\"][\"name\"]}')
" 2>/dev/null

# 5. Skills
echo "📚 Skills:"
SKILLS_DIR="$BASE_DIR/skills"
if [ -d "$SKILLS_DIR" ]; then
    count=$(ls "$SKILLS_DIR"/*.md 2>/dev/null | wc -l)
    echo -e "  ${GREEN}✅${NC} $count skills installées"
else
    echo -e "  ${YELLOW}⚠️${NC} Aucun répertoire skills/"
fi

# 6. Workspace
echo "📁 Workspace:"
[ -d "$BASE_DIR/workspace" ] && echo -e "  ${GREEN}✅${NC} Workspace présent" || echo -e "  ${YELLOW}⚠️${NC} Workspace à créer"

# 7. Provider
echo "🔗 Chaîne provider:"
$PYTHON -c "
import sys; sys.path.insert(0,'$BASE_DIR')
from core.utils import load_env; load_env('$BASE_DIR/.env')
from core.provider import _init_providers, PROVIDER_CHAIN
_init_providers()
if PROVIDER_CHAIN:
    for p in PROVIDER_CHAIN:
        print(f'  ✅ {p[\"name\"]} → {p[\"model\"]}')
else:
    print('  ❌ Aucun provider configuré')
" 2>/dev/null

echo ""
echo "================================"
echo "Résultat: ${GREEN}$pass succès${NC}, ${RED}$fail échecs${NC}"
exit $fail
