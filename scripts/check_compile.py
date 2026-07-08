#!/usr/bin/env python3
"""Vérifie que tous les fichiers .py compilent sans erreur de syntaxe.

Usage:
    python3 scripts/check_compile.py

Exit code:
    0 — tout compile
    1 — au moins un fichier a une erreur de syntaxe
"""

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SOURCES = [
    REPO_ROOT / "santana.py",
    *sorted((REPO_ROOT / "core").rglob("*.py")),
    *sorted((REPO_ROOT / "tools").rglob("*.py")),
    *sorted((REPO_ROOT / "agent").rglob("*.py")),
    *sorted((REPO_ROOT / "tests").rglob("*.py")),
    *sorted((REPO_ROOT / "scripts").rglob("*.py")),
]

EXCLUDES = {"venv", "venv_new", "__pycache__", ".eggs", "build", "dist"}

errors = []

for path in SOURCES:
    # Skip if any parent directory is excluded
    if any(part in EXCLUDES for part in path.parts):
        continue
    if not path.exists():
        continue

    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:
        errors.append((path, e))
    except Exception as e:
        errors.append((path, e))

if errors:
    print(f"❌ {len(errors)} fichier(s) avec erreur de syntaxe :\n")
    for path, err in errors:
        print(f"  {path.relative_to(REPO_ROOT)}")
        print(f"    Ligne {err.lineno or '?'}: {err.msg}")
        print()
    sys.exit(1)
else:
    total = sum(1 for p in SOURCES if p.exists())
    print(f"✅ {total} fichiers .pc compilent correctement.")
    sys.exit(0)
