# Contributing to Santana

Thanks for considering contributing! Santana is an open-source autonomous AI agent, and every contribution — whether code, documentation, bug report, or idea — is valued.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Pull Request Process](#pull-request-process)
- [Commit Messages](#commit-messages)
- [Reporting Bugs](#reporting-bugs)
- [Feature Requests](#feature-requests)

## Code of Conduct

Be respectful, constructive, and inclusive.  
Santana is built for a diverse global community — everyone is welcome.

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/santana.git
   cd santana
   ```
3. Set up the development environment (see [Development Setup](#development-setup))
4. Create a branch for your changes:
   ```bash
   git checkout -b feat/your-feature-name
   ```

## Development Setup

### Prerequisites

- Python 3.11+
- Git
- A Telegram bot token (for testing — optional for core changes)

### Setup

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install dev dependencies
pip install pytest pytest-cov pytest-timeout

# Configure environment
cp .env.example .env
# Edit .env with your API keys (minimal: DEEPSEEK_API_KEY)
```

## Running Tests

```bash
# Run the full test suite (except API-dependent tests)
python -m pytest tests/ \
  --ignore=tests/test_deepseek_client.py \
  --ignore=tests/test_100_autonomie.py \
  --ignore=tests/test_100_closure.py \
  --ignore=tests/test_100_frugalite.py \
  --ignore=tests/test_100_memoire.py \
  --ignore=tests/test_100_performances.py \
  -v --tb=short --timeout=60

# Run only system integrity tests (fastest, no external deps)
python -m pytest tests/test_system_integrity.py -v --tb=short

# Run with coverage
python -m pytest tests/ \
  --ignore=tests/test_deepseek_client.py \
  --ignore=tests/test_100_*.py \
  --cov=core --cov=tools --cov=agent --cov=scripts \
  --cov-report=term-missing

# Check that all Python files compile
python scripts/check_compile.py
```

**Important:** Before submitting a PR, ensure:
1. All existing tests pass (no regressions)
2. New code has tests
3. `python scripts/check_compile.py` passes (all .py files compile)
4. The `santana.py` entry point imports cleanly: `python -c "import ast; ast.parse(open('santana.py').read()); print('✅')"`

## Code Style

- **Python:** Follow [PEP 8](https://peps.python.org/pep-0008/) with 100-character line limit
- **Imports:** Standard lib → third-party → local (separated by blank line)
- **Type hints:** Required for all function signatures (PEP 484)
- **Docstrings:** Required for all public functions and classes (Google style preferred)
- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants
- **Comments:** French or English — both accepted. Keep comments explaining *why*, not *what*

### Linting rules (CI-enforced)

- No bare `except:` clauses — always specify exception type
- No `import *` — explicit imports only
- No unused imports or variables
- All `.py` files must compile without syntax errors

## Pull Request Process

1. **Branch from `main`** — keep your branch up to date with `main`
2. **One change per PR** — small, focused PRs are reviewed faster
3. **Keep the scope small** — a PR should do one thing and do it well
4. **Update documentation** if you change behavior, add features, or modify the API
5. **Add tests** for new functionality
6. **Ensure CI passes** — your PR must be green before review
7. **Request review** from the maintainer

### PR title format

```
type(scope): short description

Examples:
  feat(core): add vector search fallback
  fix(tools): resolve rate limit race condition
  docs: add SECURITY.md and CONTRIBUTING.md
  test: add delegation unit tests
  refactor(db): centralize SQLite connection
  chore: update pinned dependencies
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`, `ci`

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
type(optional-scope): description (max 72 chars)

Optional body, wrap at 72 characters. Explain the why, not the what.
```

## Reporting Bugs

Open a [GitHub Issue](https://github.com/BadTechResearch/santana/issues/new) with:

- **Summary** — clear title
- **Steps to reproduce** — what you did
- **Expected behavior** — what should happen
- **Actual behavior** — what actually happens
- **Environment** — Python version, OS, Santana version (commit hash)
- **Logs** — relevant log output (if applicable)

## Feature Requests

Open a [GitHub Issue](https://github.com/BadTechResearch/santana/issues/new) with:

- **Problem** — what problem does this solve?
- **Proposed solution** — how would you implement it?
- **Alternatives** — what else did you consider?
- **Context** — any additional information

---

## Questions?

Contact the maintainer:
- GitHub: [@BadTechResearch](https://github.com/BadTechResearch)
- Telegram: [@Serge](https://t.me/Serge)
