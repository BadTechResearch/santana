"""Vérifie que le rate limiting est importé et utilisable."""

import sys
sys.path.insert(0, '.')

from routes.common import rate_limit
print('✅ rate_limit importé depuis routes.common')

# Vérifie que c'est bien un décorateur
@rate_limit
def _dummy():
    return 'ok'

print('✅ rate_limit fonctionne comme décorateur')
