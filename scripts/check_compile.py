"""check_compile.py — Vérification syntaxe + intégrité réelle.

IMPORTANT : la syntaxe seule (py_compile) ne détecte PAS un import qui
référence un nom qui n'existe plus dans son module source — c'est exactement
ce qui a cassé santana.py deux fois (newsession_command, codex_command,
corrigés le 19/06/2026) sans que ce script ne s'en aperçoive. Depuis,
tests/test_system_integrity.py est le test de référence pour l'intégrité
réelle du système (imports résolus, config cohérente, registre d'outils,
auth sur les routes) ; ce script l'exécute en plus de la syntaxe.
"""
import py_compile, subprocess, sys, os

errors = []
for root, dirs, files in os.walk('.'):
    if '.git' in root or 'venv' in root or '__pycache__' in root:
        continue
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            try:
                py_compile.compile(path, doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(str(e))

if errors:
    for e in errors:
        print(f'FAIL: {e}')
    sys.exit(1)

print('ALL .py files compile OK (syntaxe)', flush=True)

print('Lancement de tests/test_system_integrity.py (intégrité réelle — référence)...', flush=True)
result = subprocess.run(
    [sys.executable, '-m', 'pytest', 'tests/test_system_integrity.py', '-q'],
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
sys.exit(result.returncode)
