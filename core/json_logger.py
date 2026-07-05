"""Logging structuré JSON pour Santana.
Ajoute un correlation_id à chaque message et émet des logs JSON parsables par jq.

Usage :
    from core.json_logger import json_log
    json_log("tool_call", tool="web_search", duration_ms=1200, status="ok")
"""

from core.utils import get_base_dir
import json
import logging
import os
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_LOG_DIR = get_base_dir()
_STRUCTURED_LOG_PATH = os.path.join(_LOG_DIR, "events.jsonl")


def json_log(event: str, **kwargs):
    """Émet un événement JSON structuré dans events.jsonl et en log INFO.

    Args:
        event: Nom de l'événement (tool_call, llm_call, error, etc.)
        **kwargs: Paires clé=valeur à inclure (correlation_id auto-généré si absent)
    """
    if "correlation_id" not in kwargs:
        kwargs["correlation_id"] = str(uuid.uuid4())[:8]
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **kwargs,
    }
    line = json.dumps(entry, ensure_ascii=False)
    try:
        with open(_STRUCTURED_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        logger.debug(f"[JSONLOG] Write error: {e}")
    # Aussi en log INFO pour les humains
    _safe = {k: v for k, v in kwargs.items() if len(str(v)) < 200}
    logger.info(f"[JSONLOG] {event} %s", json.dumps(_safe, ensure_ascii=False)[:300])
