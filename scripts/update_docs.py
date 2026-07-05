#!/usr/bin/env python3
"""Auto-update des docs Santana : SOUL.md, ARCHITECTURE.md, README.md.
Usage : python3 scripts/update_docs.py [--benchmark FILE]

Met à jour automatiquement :
- Lignes Python
- Nombre d'outils
- Nombre de tests
- Score benchmark Black Intelligence V5
- Date de mise à jour
"""
import os, sys, json, re, subprocess
from datetime import datetime
from core.utils import get_base_dir

BASE = get_base_dir()
SOUL = os.path.join(BASE, "soul", "SOUL.md")
ARCH = os.path.join(BASE, "ARCHITECTURE.md")
README = os.path.join(BASE, "README.md")
BENCH_RESULTS = os.path.join(BASE, "benchmark_results")


def count_python_lines():
    """Compte les lignes Python réelles (hors venv, archives, .git)."""
    total = 0
    for root, dirs, files in os.walk(BASE):
        # Exclure
        dirs[:] = [d for d in dirs if not d.startswith(('.', '_', 'venv', '__pycache__'))]
        for f in files:
            if f.endswith('.py'):
                path = os.path.join(root, f)
                try:
                    with open(path) as fh:
                        total += len(fh.readlines())
                except:
                    pass
    return total


def count_tests():
    """Compte les tests pytest en utilisant le bon venv."""
    # Chercher le venv
    for venv_name in ['venv_new', 'venv']:
        python = os.path.join(BASE, venv_name, 'bin', 'python')
        if os.path.exists(python):
            break
    else:
        python = sys.executable

    try:
        r = subprocess.run(
            [python, '-m', 'pytest', 'tests/', '--collect-only', '-q'],
            capture_output=True, text=True, timeout=30,
            cwd=BASE
        )
        for line in r.stdout.split('\n'):
            m = re.search(r'(\d+)\s+selected', line)
            if m:
                return int(m.group(1))
    except:
        pass
    # Fallback: compter les fonctions test_
    total = 0
    for root, dirs, files in os.walk(os.path.join(BASE, 'tests')):
        for f in files:
            if f.startswith('test_') and f.endswith('.py'):
                with open(os.path.join(root, f)) as fh:
                    for line in fh:
                        if line.strip().startswith('def test_'):
                            total += 1
    return total


def count_tools():
    """Compte les outils dans tools.json."""
    tools_path = os.path.join(BASE, "tools", "tools.json")
    try:
        with open(tools_path) as f:
            return len(json.load(f))
    except:
        return 0


def get_latest_benchmark():
    """Lit le dernier benchmark."""
    if not os.path.exists(BENCH_RESULTS):
        return None
    files = [f for f in os.listdir(BENCH_RESULTS) if f.startswith('bi_v5_santana') and f.endswith('.json')]
    if not files:
        return None
    latest = max(files, key=lambda f: os.path.getmtime(os.path.join(BENCH_RESULTS, f)))
    path = os.path.join(BENCH_RESULTS, latest)
    try:
        with open(path) as f:
            data = json.load(f)
        return {
            "score": data.get("score", "?"),
            "passed": sum(1 for r in data.get("results", []) if r.get("passed")),
            "total": len(data.get("results", [])),
            "cost": data.get("total_cost", 0),
            "latency": data.get("total_latency", 0),
            "file": latest,
        }
    except:
        return None


def update_soul_md(lines, tests, tools, bench):
    """Met à jour les stats dans SOUL.md."""
    path = SOUL
    with open(path) as f:
        content = f.read()

    now = datetime.now().strftime("%d %B %Y, %H:%M")

    # Ligne "État actuel"
    if bench:
        new_state = f"État actuel : **{lines}K lignes Python, {tools} outils, {tests} tests, benchmark Black Intelligence V5 {bench['score']}/100 ({bench['passed']}/{bench['total']}).**"
    else:
        new_state = f"État actuel : **{lines}K lignes Python, {tools} outils, {tests} tests.**"
    
    content = re.sub(
        r'État actuel : \*\*.*?\*\*',
        new_state,
        content
    )

    # Date de mise à jour
    content = re.sub(
        r'Mis à jour le :.*',
        f'Mis à jour le : {now}',
        content
    )
    if 'Mis à jour le :' not in content:
        # Ajouter après le titre si pas présent
        content = content.replace(
            '## Identité',
            f'## Identité\n\nMis à jour le : {now}'
        )
        content = content.replace(
            '# SOUL.md — Santana V3',
            f'# SOUL.md — Santana V3\n\n_Mis à jour le : {now}_'
        )

    with open(path, 'w') as f:
        f.write(content)
    print(f"✅ SOUL.md mis à jour — {lines}K lignes, {tests} tests, {tools} outils")


def update_arch_md(lines, tests, tools, bench):
    """Met à jour les stats dans ARCHITECTURE.md."""
    path = ARCH
    today = datetime.now().strftime("%d %B %Y")

    with open(path) as f:
        content = f.read()

    # Section statistiques
    new_stats = f"""## Statistiques ({today})

- **{lines:,} lignes Python**
- **{tools} outils** registrés
- **{tests} tests** unitaires
- **Benchmark Black Intelligence V5 : {bench['score']}/100** ({bench['passed']}/{bench['total']} tests)""" if bench else f"""## Statistiques ({today})

- **{lines:,} lignes Python**
- **{tools} outils** registrés
- **{tests} tests** unitaires"""

    # Remplacer la section stats existante
    if '## Statistiques' in content:
        content = re.sub(
            r'## Statistiques \(.*?\).*?(?=\n## |\Z)',
            new_stats,
            content,
            flags=re.DOTALL
        )
    else:
        content += f"\n\n{new_stats}\n"

    # Mettre à jour le nombre de lignes dans l'en-tête
    content = re.sub(
        r'# ARCHITECTURE.*',
        f'# ARCHITECTURE — Santana ({today})',
        content
    )

    with open(path, 'w') as f:
        f.write(content)
    print(f"✅ ARCHITECTURE.md mis à jour")


def update_readme(lines, tests, tools, bench):
    """Met à jour les stats dans README.md."""
    path = README
    today = datetime.now().strftime("%d %B %Y")

    with open(path) as f:
        content = f.read()

    now = datetime.now().strftime("%Y-%m-%d")

    # Section statistiques
    new_stats = f"""## 📊 Statistiques ({now})

| Métrique | Valeur |
|----------|--------|
| Lignes Python | **{lines:,}** (après purge) |
| Outils | **{tools}** |
| Tests unitaires | **{tests}** |
| Benchmark Black Intelligence V5 | **{bench['score']}/100** ({bench['passed']}/{bench['total']} tests) |
| Coût/run benchmark | **€{bench['cost']:.4f}** |
| Latence moyenne | **{bench['latency']/max(bench['total'],1):.2f}s** |
| Budget mensuel | **~€4.80/mois** |""" if bench else f"""## 📊 Statistiques ({now})

| Métrique | Valeur |
|----------|--------|
| Lignes Python | **{lines:,}** |
| Outils | **{tools}** |
| Tests unitaires | **{tests}** |"""

    if '## 📊 Statistiques' in content:
        content = re.sub(
            r'## 📊 Statistiques.*?(?=\n## |\Z)',
            new_stats,
            content,
            flags=re.DOTALL
        )
    else:
        content = content.replace(
            '## 🏗️ Architecture',
            f'{new_stats}\n\n## 🏗️ Architecture'
        )

    with open(path, 'w') as f:
        f.write(content)
    print(f"✅ README.md mis à jour")


def main():
    bench = get_latest_benchmark()
    lines_raw = count_python_lines()
    lines_k = round(lines_raw / 1000, 1)
    tests = count_tests()
    tools = count_tools()

    print(f"📊 Lignes Python : {lines_raw:,} ({lines_k}K)")
    print(f"🔧 Outils : {tools}")
    print(f"🧪 Tests : {tests}")
    if bench:
        print(f"🏆 Benchmark : {bench['score']}/100 ({bench['passed']}/{bench['total']})")
    else:
        print("🏆 Benchmark : aucun résultat trouvé")

    update_soul_md(lines_k, tests, tools, bench)
    update_arch_md(lines_raw, tests, tools, bench)
    update_readme(lines_raw, tests, tools, bench)

    print("\n✅ Tous les documents mis à jour.")


if __name__ == "__main__":
    main()
