"""Configuration globale des tests Santana."""
import os

# Clé API DeepSeek pour les tests — évite les RuntimeError early-exit
os.environ.setdefault("DEEPSEEK_API_KEY", "test_key_for_tests")
