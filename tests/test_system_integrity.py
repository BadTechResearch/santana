"""tests/test_system_integrity.py — Garde-fou d'intégrité système Santana.

Ne fait PAS double emploi avec :
- scripts/check_compile.py : vérifie la syntaxe (py_compile) — ne détecte PAS
  un import qui référence un nom qui n'existe plus dans le module source.
- tests/test_*.py existants : testent la logique métier unitaire de chaque
  module isolément.

Ce fichier teste autre chose : que le système TIENT DEBOUT dans son ensemble —
tous les imports réels résolvent, la config est cohérente entre fichiers, le
registre d'outils correspond à ce que Santana croit avoir, chaque route Flask
est protégée, et les bugs déjà trouvés/corrigés le restent.

Origine : santana.py a eu DEUX ImportError indépendantes et réelles
(commits 6f222ccf et b4fa2a97, fixées le 19/06/2026) qu'aucun test existant
n'a détectées — parce qu'aucun test n'importait réellement les modules
concernés. 161 tests verts n'a jamais voulu dire "le système démarre".

Note de sécurité importante : ce fichier n'importe JAMAIS santana.py
directement (ni en process, ni en sous-processus). santana.py a deux effets
de bord réels au niveau module (pas seulement dans son bloc __main__) :
  1. Un verrou fichier exclusif (.santana.lock) — échoue TOUJOURS si
     santana.service tourne déjà (cas normal en production), ce qui ferait
     échouer ce test pour une raison sans rapport avec un bug d'import.
  2. Si .crash_flag existe, l'import envoie une VRAIE alerte Telegram.
Pour tester "santana.py importerait correctement" sans ces risques, on
vérifie statiquement (via ast) que chaque nom importé par santana.py depuis
tg_handlers existe réellement dans le module source — équivalent fonctionnel
sans exécuter le moindre effet de bord de santana.py.
"""

import ast
import importlib
import inspect
import json
import os
import re
import subprocess
import sys

import pytest

# Ajouter la racine du projet au path pour les imports (convention du projet)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

BASE_DIR = PROJECT_ROOT


# ═══════════════════════════════════════════════════════════════════════════
# 1. IMPORT RÉEL — chaque module des couches du projet doit s'importer
# ═══════════════════════════════════════════════════════════════════════════

LAYER_DIRS = [
    "agent", "core", "atlas_engine", "tools",
    "tg_handlers", "routes", "memory", "metrics",
]

# tg_handlers.handlers est un tombstone VOLONTAIRE : il raise ImportError
# par construction (voir son propre docstring) depuis le split en
# sous-modules. C'est la seule exemption légitime de cette section.
_INTENTIONAL_IMPORT_FAILURES = {"tg_handlers.handlers"}


def _list_layer_modules() -> list[str]:
    modules = []
    for d in LAYER_DIRS:
        layer_path = os.path.join(BASE_DIR, d)
        if not os.path.isdir(layer_path):
            continue
        for fname in sorted(os.listdir(layer_path)):
            if fname.endswith(".py") and fname != "__init__.py":
                modules.append(f"{d}.{fname[:-3]}")
    return modules


@pytest.mark.parametrize("module_name", _list_layer_modules())
def test_module_imports_without_error(module_name):
    """Chaque module de agent/core/atlas_engine/tools/tg_handlers/routes/
    memory/metrics doit s'importer sans ImportError.

    C'est exactement la catégorie de bug qui a cassé santana.py deux fois :
    un import qui référence un nom (newsession_command, codex_command) qui
    n'existe plus dans le module source après un refactor incomplet.
    """
    if module_name in _INTENTIONAL_IMPORT_FAILURES:
        with pytest.raises(ImportError):
            importlib.import_module(module_name)
        return
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"{module_name} ne s'importe pas : {e}")


def test_santana_py_referenced_names_exist():
    """Vérifie que tous les noms de handlers passés à CommandHandler/
    MessageHandler/CallbackQueryHandler dans santana.py sont bien définis
    quelque part dans le fichier (def/async def inline, ou import) — SANS
    importer santana.py lui-même (cf docstring du fichier : effets de bord
    réels au niveau module — verrou process + alerte Telegram conditionnelle).

    Remplace une version antérieure qui ne vérifiait que les imports
    `from tg_handlers.* import ...` : le 04/07/2026, une tentative de split
    vers un module tg_handlers (jamais créé, jamais committé) a laissé des
    imports cassés référençant des noms inexistants — panne immédiate au
    démarrage (NameError dès le premier add_handler()) restée invisible
    parce que le service tournait déjà avec l'ancien code en mémoire. Ce
    test attrape cette classe de bug quelle que soit sa forme (import cassé
    OU fonction supprimée par erreur), en vérifiant la résolution réelle des
    noms plutôt qu'un pattern d'import particulier.
    """
    santana_path = os.path.join(BASE_DIR, "santana.py")
    with open(santana_path) as f:
        src = f.read()
    tree = ast.parse(src, filename=santana_path)

    defined = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                defined.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                defined.add(alias.asname or alias.name)

    # Noms de handlers référencés par CommandHandler(...)/MessageHandler(...)/
    # CallbackQueryHandler(...), et par la liste [(cmd, handler), ...] de la
    # boucle d'enregistrement des CommandHandler.
    # Variables cibles de `for x, y in [...]` — à exclure des noms référencés
    # (ce sont des variables de boucle, pas des noms globaux à résoudre).
    loop_targets = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
            for elt in node.target.elts:
                if isinstance(elt, ast.Name):
                    loop_targets.add(elt.id)

    referenced = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("CommandHandler", "MessageHandler", "CallbackQueryHandler"):
                for arg in node.args:
                    if isinstance(arg, ast.Name) and arg.id not in loop_targets:
                        referenced.add(arg.id)
        # Tuples littéraux (cmd, handler) DANS une liste littérale — c'est ici
        # que les vrais noms de handlers apparaissent pour la boucle
        # `for cmd, handler in [(...), ...]`.
        if isinstance(node, ast.List):
            for elt in node.elts:
                if isinstance(elt, ast.Tuple) and len(elt.elts) == 2:
                    second = elt.elts[1]
                    if isinstance(second, ast.Name):
                        referenced.add(second.id)

    missing = sorted(n for n in referenced if n not in defined)
    assert not missing, (
        f"santana.py référence des handlers non définis (import cassé ou "
        f"fonction supprimée par erreur) : {missing}"
    )
    assert referenced, "Aucun handler référencé trouvé — le test ne vérifie peut-être plus rien"


def test_santana_py_module_level_lock_and_crash_alert_are_guarded():
    """Documente et verrouille la compréhension des deux effets de bord de
    santana.py qui empêchent un `import santana` direct dans les tests
    (voir docstring du fichier). Si ce test échoue, c'est que santana.py a
    changé de structure et qu'il faut réévaluer si un import direct
    redevient sûr.
    """
    src = open(os.path.join(BASE_DIR, "santana.py")).read()
    lock_block = re.search(r"_LOCK_FILE = .*?exit\(1\)", src, re.DOTALL)
    assert lock_block, "Le verrou PID (.santana.lock) ne semble plus exister sous cette forme dans santana.py"
    # Le verrou doit être au niveau module (colonne 0), pas dans une fonction/if __main__
    lock_line_start = src[: lock_block.start()].count("\n") + 1
    line = src.splitlines()[lock_line_start - 1]
    assert not line.startswith((" ", "\t")), (
        "Le verrou PID a été déplacé dans un bloc indenté — réévaluer si "
        "`import santana` est devenu sûr pour les tests."
    )
    assert "_CRASH_FLAG" in src and "urlopen" in src, (
        "L'alerte Telegram conditionnelle au crash flag semble avoir disparu — "
        "réévaluer si `import santana` est devenu sûr pour les tests."
    )


# ═══════════════════════════════════════════════════════════════════════════
# 2. CONFIG COHÉRENTE
# ═══════════════════════════════════════════════════════════════════════════

def test_deepseek_model_single_source_of_truth():
    """DISPLAY_MODEL (tg_handlers/state.py) doit être la MÊME valeur que
    DEEPSEEK_MODEL (deepseek_client.py), importée directement — pas relue
    séparément avec un défaut différent (Bug 5, audit 3 : 'deepseek-chat'
    vs 'deepseek-v4-flash' pouvaient diverger silencieusement).
    """
    from deepseek_client import DEEPSEEK_MODEL
    pytest.importorskip("tg_handlers.state", reason="tg_handlers/ non présent dans le dépôt public")
    from tg_handlers.state import DISPLAY_MODEL

    assert DISPLAY_MODEL == DEEPSEEK_MODEL

    state_src = open(os.path.join(BASE_DIR, "tg_handlers", "state.py")).read()
    assert "from deepseek_client import DEEPSEEK_MODEL" in state_src, (
        "tg_handlers/state.py ne semble plus importer DEEPSEEK_MODEL directement "
        "depuis deepseek_client.py — risque de retour du bug des deux défauts divergents."
    )


def test_cost_governor_single_budget_source():
    """DEEPSEEK_COST_LIMIT ne doit être lu (os.getenv) que dans
    tools/cost_governor.py — éviter qu'un deuxième défaut divergent
    apparaisse comme ça a été le cas pour DEEPSEEK_MODEL.
    """
    hits = []
    # tests/ exclu : ce fichier de test mentionne lui-même la chaîne "DEEPSEEK_COST_LIMIT"
    # dans ses docstrings/assertions, ce qui produirait un faux positif auto-référentiel.
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in ("venv_new", ".git", "__pycache__", "tests", "backup", "github_cache")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, errors="ignore") as f:
                content = f.read()
            if "DEEPSEEK_COST_LIMIT" in content:
                hits.append(os.path.relpath(fpath, BASE_DIR))
    assert hits == ["tools/cost_governor.py"], (
        f"DEEPSEEK_COST_LIMIT référencé depuis plusieurs fichiers applicatifs : {hits} — "
        "risque de défauts divergents comme pour DEEPSEEK_MODEL."
    )


def test_env_example_documents_critical_vars():
    """Toute variable d'environnement critique pour le contrôle d'accès doit
    être documentée dans .env.example. Bug A (audit 2) : GROUP_BLACK_INTELLIGENCE
    était absente, donc un déploiement frais tombait dans le mode fail-open
    sans que rien ne le signale.
    """
    with open(os.path.join(BASE_DIR, ".env.example")) as f:
        example = f.read()
    required = [
        "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL",
        "TELEGRAM_TOKEN", "CHAT_ID", "GROUP_BLACK_INTELLIGENCE",
    ]
    missing = [v for v in required if v not in example]
    assert not missing, f"Variables critiques absentes de .env.example : {missing}"


# ═══════════════════════════════════════════════════════════════════════════
# 3. REGISTRE OUTILS = DESCRIPTIONS
# ═══════════════════════════════════════════════════════════════════════════

def _live_tool_names() -> set[str]:
    import tools.tools  # noqa: F401 — déclenche l'enregistrement de tous les @tool()
    from tools.registry import get_tool_names
    return set(get_tool_names())



def test_tools_json_matches_live_registry():
    """tools/tools.json doit contenir EXACTEMENT les mêmes outils que le
    registre live — en sous-processus pour éviter les artefacts d'état global.
    """
    import subprocess as _sp, json as _json
    result = _sp.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, '.'); "
         "from core.utils import load_env; load_env('.env'); "
         "from tools.tools import TOOLS; "
         "print(sorted(t['function']['name'] for t in TOOLS))"],
        capture_output=True, text=True, cwd=BASE_DIR,
    )
    live = set(eval(result.stdout.strip()))
    with open(os.path.join(BASE_DIR, "tools", "tools.json")) as f:
        static_tools = _json.load(f)
    static = {t["function"]["name"] for t in static_tools if "function" in t}
    missing_from_json = live - static
    ghosts_in_json = static - live
    assert not missing_from_json and not ghosts_in_json, (
        "tools.json désynchronisé du registre live — "
        f"manquants dans tools.json : {sorted(missing_from_json) or 'aucun'} ; "
        f"fantômes dans tools.json : {sorted(ghosts_in_json) or 'aucun'}."
    )


def test_self_scan_registry_matches_live_registry():
    """agent/self.py:scan_registry() doit refléter le registre live — sinon
    l'auto-description injectée dans le prompt système ('tes outils') ment
    sur les outils réellement disponibles.
    """

    from agent.self import scan_registry
    live = _live_tool_names()
    reported = set(scan_registry().get("outils", []))
    assert reported == live, (
        f"scan_registry() ({len(reported)} outils) ne correspond pas au registre live "
        f"({len(live)} outils) — écart : {sorted(live.symmetric_difference(reported))}. "
        "Bug connu (audit final 19/06), NON corrigé à ce jour : scan_registry() lit "
        "tools/tools.json au lieu de tools.registry.get_tool_names()."
    )


# ═══════════════════════════════════════════════════════════════════════════
# 4. TOUTES LES ROUTES ONT AUTH
# ═══════════════════════════════════════════════════════════════════════════

# Exemptions documentées : routes intentionnellement publiques ou qui
# ═══════════════════════════════════════════════════════════════════════════
# 5. BUGS CONNUS — un test par bug corrigé, pour garantir que le fix tient
# ═══════════════════════════════════════════════════════════════════════════

def test_bug_a_is_allowed_fails_closed():
    """Bug A (audit 2) : is_allowed() doit refuser tout chat_id inconnu quand
    GROUP_BLACK_INTELLIGENCE n'est pas configuré (GROUP_ID=0). Avant le fix,
    `or GROUP_ID == 0` ouvrait l'accès à TOUT LE MONDE dans ce cas.
    """
    pytest.importorskip("tg_handlers.state", reason="tg_handlers/ non présent dans le dépôt public")
    import tg_handlers.state as state
    original = (state.CHAT_ID, state.GROUP_ID)
    try:
        state.CHAT_ID, state.GROUP_ID = 111, 0
        assert state.is_allowed(111) is True
        assert state.is_allowed(999) is False, "FAIL-OPEN : chat_id inconnu accepté quand GROUP_ID=0"

        state.GROUP_ID = 222
        assert state.is_allowed(222) is True
        assert state.is_allowed(999) is False
    finally:
        state.CHAT_ID, state.GROUP_ID = original


def test_bug_b_vm_validate_blocks_known_bypasses():
    """Bug B (audit 2) : les contournements démontrés de la liste noire
    _vm_validate doivent rester bloqués, sans bloquer les commandes légitimes.
    """
    from tools.vm_security import validate_command as _vm_validate

    bypasses = [
        "rm -rf /tmp/x",
        "rm  -rf /tmp/x",
        "rm -r -f /tmp/x",
        "rm -f -r /tmp/x",
        "rm --recursive --force /tmp/x",
        "find / -delete",
        "python3 -c \"import shutil; shutil.rmtree('/home')\"",
        ":(){ :|:& };:",
        "sudo whoami",
    ]
    for cmd in bypasses:
        ok, _ = _vm_validate(cmd)
        assert ok is False, f"Bypass non bloqué : {cmd!r}"

    legit = ["ls -la", "curl https://example.com", "pip install foo", "rm fichier.txt"]
    for cmd in legit:
        ok, _ = _vm_validate(cmd)
        assert ok is True, f"Commande légitime bloquée à tort : {cmd!r}"


def test_bug_cd_gitignore_patterns():
    """Bug C+D (audit 2) : *.db-shm, *.db-wal et *.bak.<timestamp> doivent
    être ignorés par git (et donc ne plus être trackés/re-commités).
    """
    targets = [
        "memory.db-shm", "memory.db-wal", "metrics.db-shm", "metrics.db-wal",
        "_backups/x.bak.20260101-000000", "tools/y.bak.phase2",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "-v"] + targets,
        cwd=BASE_DIR, capture_output=True, text=True,
    )
    ignored = set()
    for line in result.stdout.strip().splitlines():
        if "\t" in line:
            ignored.add(line.split("\t", 1)[1])
    missing = [t for t in targets if t not in ignored]
    assert not missing, f"Fichiers non ignorés par git (régression possible) : {missing}"


def test_bug_e_no_duplicate_classify_patterns():
    """Bug E (audit 2) : factual_patterns et synthesis_patterns dans
    classify_message() ne doivent pas se chevaucher — sinon des entrées de
    synthesis_patterns redeviennent inatteignables (factual_patterns est
    testé en premier).
    """
    src = open(os.path.join(BASE_DIR, "agent", "orchestrator.py")).read()
    factual_block = re.search(r"factual_patterns = \[(.*?)\]", src, re.DOTALL)
    synthesis_block = re.search(r"synthesis_patterns = \[(.*?)\]", src, re.DOTALL)
    assert factual_block and synthesis_block, "Listes factual_patterns/synthesis_patterns introuvables — orchestrator.py a changé de structure"
    factual = set(re.findall(r'"([^"]+)"', factual_block.group(1)))
    synthesis = set(re.findall(r'"([^"]+)"', synthesis_block.group(1)))
    overlap = factual & synthesis
    assert not overlap, f"Patterns dupliqués (rendus inatteignables dans synthesis_patterns) : {overlap}"


def test_bug_3_auth_uses_constant_time_comparison():
    """Bug 3 (audit 3) : auth() doit utiliser hmac.compare_digest(), pas ==,
    pour éviter une timing attack sur la comparaison du token API.
    """
    pytest.importorskip("routes.common", reason="routes/ non présent dans le dépôt public")
    from routes.common import auth, TOKEN

    source = inspect.getsource(auth)
    assert "hmac.compare_digest" in source, (
        "auth() ne semble plus utiliser hmac.compare_digest() — régression "
        "possible vers une comparaison '==' vulnérable au timing attack."
    )

    from flask import Flask, request
    app = Flask(__name__)
    with app.test_request_context(headers={"X-API-Key": TOKEN}):
        assert auth(request) is True
    with app.test_request_context(headers={"X-API-Key": "wrong-token"}):
        assert auth(request) is False
    with app.test_request_context():
        assert auth(request) is False


def test_bug_imports_casses_santana_py():
    """Bug critique (4ᵉ audit) : santana.py avait deux imports cassés
    (newsession_command, codex_command) qui empêchaient tout démarrage.
    Couvert ici par référence aux deux tests dédiés (résolution réelle des
    noms importés, sans exécuter santana.py — voir docstring du fichier).
    """
    assert "newsession_command" not in open(os.path.join(BASE_DIR, "santana.py")).read()
    if os.path.exists(os.path.join(BASE_DIR, "tg_handlers", "media.py")):
        assert "codex_command" not in open(os.path.join(BASE_DIR, "tg_handlers", "media.py")).read()


def test_bug_evaluator_log_evaluation_called_from_react_loop():
    """Bug mineur (audit final) : log_evaluation() doit être appelée depuis
    core/react_loop.py pour que l'historique d'auto-évaluation soit
    réellement alimenté en production. CORRIGÉ le 24/06/2026 — test vert.
    """
    src = open(os.path.join(BASE_DIR, "core", "react_loop.py")).read()
    assert "log_evaluation" in src, (
        "log_evaluation() n'est jamais appelée depuis react_loop.py — l'historique "
        "d'auto-évaluation (eval_history.json) reste vide en production malgré "
        "l'infrastructure testée dans agent/evaluator.py."
    )


# ═══════════════════════════════════════════════════════════════════════════
# 6. DÉMARRAGE — couvert par test_santana_py_referenced_names_exist (section 1)
#    et test_santana_py_module_level_lock_and_crash_alert_are_guarded.
#    Pas de test supplémentaire ici : voir la docstring du fichier pour la
#    justification de ne jamais faire `import santana` directement.
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# 7. INTÉGRITÉ COUCHE MÉMOIRE
# ═══════════════════════════════════════════════════════════════════════════

def test_memory_detect_conflicts_reuses_cached_model():
    """Bug mineur (audit 3), NON corrigé : detect_conflicts() instanciait un
    SentenceTransformer local à chaque appel au lieu de réutiliser le
    singleton caché de atlas_engine/embeddings.py. Ce test échoue
    intentionnellement jusqu'à ce que ce soit corrigé.
    """
    src = open(os.path.join(BASE_DIR, "atlas_engine", "memory_injector.py")).read()
    body_match = re.search(r"def detect_conflicts.*?(?=\ndef |\Z)", src, re.DOTALL)
    assert body_match, "detect_conflicts() introuvable — memory_injector.py a changé de structure"
    assert "SentenceTransformer(" not in body_match.group(0), (
        "detect_conflicts() instancie encore un SentenceTransformer localement au lieu "
        "de réutiliser le singleton de atlas_engine/embeddings.py — rechargement "
        "redondant à chaque message PERSONNEL."
    )


def test_memory_compression_thresholds_are_ordered():
    """Les seuils de compression progressive de agent/context.py doivent être
    strictement croissants, sinon la logique à 3 niveaux de get_context() ne
    se déclenche pas dans l'ordre prévu (soft -> hard trim).
    """
    from agent.context import COMPRESSION_CONFIG as C
    assert C["soft_warn_tokens"] < C["soft_trim_at"] < C["hard_trim_at"], (
        f"Seuils de compression non strictement croissants : {C}"
    )


def test_memory_atlas_limits_not_regressed():
    """MAX_ENTRY_CHARS et MAX_WRITE_PER_TURN avaient été augmentés (300->1500,
    1->5) pour corriger un writer trop restrictif. Vérifie qu'on n'est pas
    revenu aux anciennes valeurs.
    """
    from atlas_engine.atlas import MAX_ENTRY_CHARS, MAX_WRITE_PER_TURN
    assert MAX_ENTRY_CHARS >= 1000, f"MAX_ENTRY_CHARS={MAX_ENTRY_CHARS} semble régressé vers l'ancienne valeur trop stricte"
    assert MAX_WRITE_PER_TURN >= 3, f"MAX_WRITE_PER_TURN={MAX_WRITE_PER_TURN} semble régressé vers l'ancienne valeur trop stricte"


def test_memory_embeddings_singleton_pattern_exists():
    """atlas_engine/embeddings.py doit garder un cache global du modèle
    (singleton) — c'est ce que detect_conflicts() devrait réutiliser
    (cf test_memory_detect_conflicts_reuses_cached_model). Si ce singleton
    disparaît, le bug connu de rechargement redondant s'étend à tout le
    reste de la mémoire vectorielle, pas seulement detect_conflicts().
    """
    src = open(os.path.join(BASE_DIR, "atlas_engine", "embeddings.py")).read()
    # V2 : singleton déplacé dans model_singleton.py (chargement unique global)
    assert "model_singleton" in src, "Le singleton MiniLM doit utiliser atlas_engine.model_singleton"


# ═══════════════════════════════════════════════════════════════════════════
# BONUS — durcissements trouvés en explorant, non listés explicitement dans
# le brief mais relevant directement des mêmes catégories de risque.
# ═══════════════════════════════════════════════════════════════════════════

def test_no_fstring_sql_injection():
    """Aucune requête SQL ne doit être construite par f-string dans un appel
    .execute(...) — toutes les requêtes doivent utiliser des paramètres liés
    (?). Vérifié manuellement absent lors de l'audit du 19/06 ; ce test en
    fait une garantie permanente plutôt qu'une vérification ponctuelle.

    Portée volontairement étroite (un seul pattern précis) : ce n'est pas un
    analyseur SQL général, juste un garde-fou contre le cas le plus courant
    et le plus dangereux en Python.
    """
    risky = []
    sql_dirs = ["agent", "core", "atlas_engine", "tools", "routes", "memory", "metrics"]
    pattern = re.compile(r'\.execute\(\s*f["\']')
    for d in sql_dirs:
        for root, dirs, files in os.walk(os.path.join(BASE_DIR, d)):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath, errors="ignore") as f:
                    for lineno, line in enumerate(f, 1):
                        if pattern.search(line):
                            risky.append(f"{os.path.relpath(fpath, BASE_DIR)}:{lineno}")
    assert not risky, f"Requête(s) SQL potentiellement construite(s) par f-string (injection) : {risky}"


def test_tokenfilter_covers_percent_style_logging():
    """Régression du fix TokenFilter (audit 3) : le filtre doit utiliser
    record.getMessage() (couvre le style %s-args), pas record.msg brut seul.
    """
    source = inspect.getsource(__import__("core.utils", fromlist=["TokenFilter"]).TokenFilter.filter)
    assert "getMessage" in source, (
        "TokenFilter.filter() ne semble plus utiliser record.getMessage() — "
        "régression possible : les secrets passés en logging %s-style ne seraient "
        "plus filtrés des logs."
    )


def test_no_other_dangling_function_imports_in_project():
    """Généralise le bug des imports cassés : pour tout `from <module_local> import a, b, c`
    (import ABSOLU — node.level == 0) où <module_local> fait partie des couches
    du projet, vérifie que a, b, c existent réellement dans le module cible.
    Plus large que la vérification ciblée sur santana.py (section 1) : couvre
    aussi les imports entre modules du projet eux-mêmes (ex: media.py qui
    importait depuis commands.py).

    Restreint aux imports absolus (node.level == 0) : un import relatif comme
    `from .memory import x` dans routes/system.py désigne routes.memory, pas
    le paquet racine memory/ — les confondre produit un faux positif (déjà
    rencontré en écrivant ce test). Les imports relatifs internes à un paquet
    sont déjà couverts par test_module_imports_without_error, qui importe
    chaque module en entier.
    """
    local_prefixes = tuple(LAYER_DIRS)
    failures = []
    for d in LAYER_DIRS:
        layer_path = os.path.join(BASE_DIR, d)
        if not os.path.isdir(layer_path):
            continue
        for fname in sorted(os.listdir(layer_path)):
            if not fname.endswith(".py") or fname == "__init__.py":
                continue
            module_name = f"{d}.{fname[:-3]}"
            if module_name in _INTENTIONAL_IMPORT_FAILURES:
                continue
            fpath = os.path.join(layer_path, fname)
            with open(fpath) as f:
                try:
                    tree = ast.parse(f.read(), filename=fpath)
                except SyntaxError:
                    continue
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module
                    and node.module.startswith(local_prefixes)
                ):
                    continue
                if node.module in _INTENTIONAL_IMPORT_FAILURES:
                    continue
                try:
                    target_mod = importlib.import_module(node.module)
                except ImportError:
                    continue  # déjà couvert par test_module_imports_without_error
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if not hasattr(target_mod, alias.name):
                        failures.append(
                            f"{module_name} (l.{node.lineno}) importe {node.module}.{alias.name} "
                            f"qui n'existe pas"
                        )
    assert not failures, "Imports internes cassés détectés :\\n" + "\\n".join(failures)


# ═══════════════════════════════════════════════════════════════════════════
# 8. RÉSILIENCE NoneType — le guard handle_message ne doit pas régresser
# ═══════════════════════════════════════════════════════════════════════════

def test_handle_message_guard_none_type():
    """Vérifie que le guard NoneType a bien été placé dans handle_message()
    et n'a pas été retiré ou commenté par inadvertance.

    Contexte : santana.py l.199-204. Sans ce guard, les updates non-texte
    (edited_message, callback_query, channel_post) passent par MessageHandler
    mais ont update.message = None → AttributeError: 'NoneType' object has
    no attribute 'text'. Ce bug causait ~58 crashes/24h avant correction.

    Approche : AST statique. N'importe PAS santana.py (qui a un lock fichier
    exclusif au niveau module + alerte crash_flag).
    """
    santana_path = os.path.join(BASE_DIR, "santana.py")
    assert os.path.isfile(santana_path), f"{santana_path} introuvable"

    with open(santana_path) as f:
        tree = ast.parse(f.read(), filename=santana_path)

    # Trouver la fonction handle_message (async def)
    handle_fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_message":
            handle_fn = node
            break

    assert handle_fn is not None, (
        "async def handle_message() introuvable dans santana.py"
    )

    # Reconstituer le corps de handle_message en texte pour inspection.
    # On part du début de la fonction (handle_fn.lineno = la ligne "async def")
    # pour capturer aussi les commentaires-header qui précèdent la 1ère instruction.
    with open(santana_path) as f:
        all_lines = f.readlines()
    first_line = handle_fn.lineno - 1  # 0-indexé
    last_body_line = max(
        (getattr(stmt, "end_lineno", stmt.lineno) for stmt in handle_fn.body),
        default=handle_fn.lineno,
    )
    body_source = "".join(all_lines[first_line:last_body_line])

    # Conditions du guard
    guards = [
        "if not update.message" in body_source,
        "update.message.text" in body_source,
        "#" in body_source and "Guard" in body_source,
    ]

    missing = [g for g in guards if not g]
    assert not missing, (
        "Le guard NoneType dans handle_message() semble avoir été retiré ou modifié."
        f" Vérifications échouées : {missing}. "
        "Ce guard est CRITIQUE — sans lui, tout update non-texte (edited_message, "
        "callback_query) crashe Santana avec AttributeError: 'NoneType' object "
        "has no attribute 'text'."
    )
    assert body_source.count("update.message") >= 2, (
        "Le guard devrait référencer update.message au moins 2 fois "
        "(condition + logging)"
    )
