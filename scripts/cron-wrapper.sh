#!/usr/bin/env bash
# cron-wrapper.sh — Active la venv Santana puis exécute la commande.
# Usage : cron-wrapper.sh <commande> [args...]
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 1
source venv_new/bin/activate
exec "$@"
