#!/usr/bin/env bash
# Audit sécurité Santana — vérifie qu'aucun secret ne fuit
set -e
PROJECT_DIR="$HOME/santana"
cd "$PROJECT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
pass() { echo -e "  ${GREEN}✅${NC} $1"; }
fail() { echo -e "  ${RED}❌${NC} $1"; ok=0; }
ok=1

echo "🔒 Audit sécurité Santana"
echo "========================"

# 1. .gitignore
echo ""
echo "1. Fichiers exclus du git"
if grep -q '.env' .gitignore 2>/dev/null; then
  pass ".env dans .gitignore"
else
  fail ".env PAS dans .gitignore"
fi
if grep -q '\.log' .gitignore 2>/dev/null; then
  pass "*.log dans .gitignore"
else
  fail "*.log PAS dans .gitignore"
fi

# 2. .env permissions
echo ""
echo "2. Permissions fichiers sensibles"
for f in "$PROJECT_DIR/.env" "$HOME/.hermes/.env"; do
  if [ -f "$f" ]; then
    perm=$(stat -c "%a" "$f" 2>/dev/null || stat -f "%p" "$f" 2>/dev/null)
    if [ "$perm" = "600" ]; then
      pass "$f → $perm"
    else
      fail "$f → $perm (devrait être 600)"
    fi
  fi
done

# 3. Tokens hardcodés dans le code
echo ""
echo "3. Tokens hardcodés dans les sources"
matches=$(find . -name '*.py' -not -path './venv/*' \
  -exec grep -ln -E '"sk-[a-zA-Z0-9]{20,}"|"ntn_[a-zA-Z0-9]{20,}"|"lin_api_[a-zA-Z0-9]{20,}"|"ghp_[a-zA-Z0-9]{20,}"' {} \; 2>/dev/null || true)
if [ -z "$matches" ]; then
  pass "Aucun token hardcodé"
else
  fail "Tokens suspects dans: $matches"
fi

# 4. Logs contenant des tokens
echo ""
echo "4. Logs sans données sensibles"
logfile="$PROJECT_DIR/hermes.log"
if [ -f "$logfile" ]; then
  hits=$(grep -ciE '(key|token|secret)=' "$logfile" 2>/dev/null || true)
  if [ "$hits" = "0" ]; then
    pass "Logs propres"
  else
    fail "$hits lignes suspectes dans hermes.log"
  fi
fi

# 5. .gitignore couvre les fichiers de backup
echo ""
echo "5. Backups exclus du git"
if grep -q '\.bak' .gitignore 2>/dev/null; then
  pass "*.bak dans .gitignore"
else
  fail "*.bak PAS dans .gitignore"
fi

echo ""
echo "========================"
if [ "$ok" -eq 1 ]; then
  echo -e "${GREEN}✅ Audit terminé : tout est vert${NC}"
else
  echo -e "${RED}❌ Audit terminé : des problèmes détectés${NC}"
  exit 1
fi
