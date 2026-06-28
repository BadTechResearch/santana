"""Singleton global pour le modèle d'embeddings MiniLM.

Évite de charger 3× le même modèle (~2.2 Go RAM chacun).
Utilisation unique : from atlas_engine.model_singleton import get_model
"""

_MODEL = None
_MODEL_NAME = "all-MiniLM-L6-v2"


def get_model():
    """Retourne l'instance unique de SentenceTransformer (chargement lazy)."""
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer(_MODEL_NAME, device="cpu", trust_remote_code=True)
    return _MODEL


def get_model_name() -> str:
    return _MODEL_NAME
