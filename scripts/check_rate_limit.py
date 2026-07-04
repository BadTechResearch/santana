"""Vérifie que le rate limiting est importé et utilisable via agent/securite.py."""
import sys
sys.path.insert(0, '.')

from agent.securite import check_rate_limit, log_access, check_tool_rate_limit
print('✅ rate_limit importé depuis agent.securite')

# Vérifie le fonctionnement basique
ok = check_rate_limit("test_check", max_calls=100, window_seconds=60)
assert ok, "check_rate_limit devrait retourner True (nouvelle clé)"
print('✅ check_rate_limit("test_check") = True')

# Vérifie check_tool_rate_limit
ok, msg = check_tool_rate_limit("test_tool")
assert ok, "check_tool_rate_limit devrait retourner True"
print(f'✅ check_tool_rate_limit("test_tool") = ({ok}, "{msg}")')

# Vérifie log_access
result = log_access("test", "check", "ok")
assert result["utilisateur"] == "test"
print(f'✅ log_access("test", "check", "ok") = OK')

print('\n✅ Tous les checks rate limit passent')
