"""
metrics — Module de métriques et d'auto-diagnostic pour Santana.

Fournit le décorateur @track() pour capturer automatiquement :
    - nom de l'outil
    - succès/échec
    - latence (ms)
    - type d'erreur

Tables SQLite :
    - tool_calls    : journal brut de chaque appel outil
    - errors        : compteur d'erreurs par type
    - improvements   : journal des patches appliqués
"""

from .recorder import track, init_metrics_db, record_tool_call, record_error

__all__ = ["track", "init_metrics_db", "record_tool_call", "record_error"]
