"""Utilitaires partagés : strip_dsml, load_env, TokenFilter."""

import os
import re
import logging


def load_env(path):
    """Charge un fichier .env dans os.environ si la clé n'est pas déjà définie."""
    if not os.path.exists(path):
        return
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value


class TokenFilter(logging.Filter):
    """Filtre le token Telegram des logs pour ne pas l'exposer."""

    def filter(self, record):
        secrets = {
            'TELEGRAM_TOKEN': os.getenv('TELEGRAM_TOKEN', ''),
            'DEEPSEEK_API_KEY': os.getenv('DEEPSEEK_API_KEY', '') or os.getenv('DEEPSEEK_KEY', ''),
            'SERPER_KEY': os.getenv('SERPER_KEY', ''),
            'CONSOLE_TOKEN': os.getenv('CONSOLE_TOKEN', ''),
            'GROQ_KEY': os.getenv('GROQ_KEY', ''),
        }
        # record.msg seul ne contient pas les valeurs passées en arguments %s-style
        # (ex: logging.info("token=%s", val)) — getMessage() fusionne msg + args.
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        for name, val in secrets.items():
            if val and val in msg:
                msg = msg.replace(val, f'[{name}]')
        record.msg = msg
        record.args = None  # déjà fusionné dans msg, éviter un second formatage
        return True


def strip_dsml(text: str) -> str:
    """Supprime les blocs DSML que DeepSeek laisse parfois dans ses réponses.

    DeepSeek V4 Flash peut insérer :
      - Des blocs complets <|DSML|>...<|/DSML|> (tool calls, CoT)
      - Des balises isolées <|DSML|>, <||DSML||>, <|/DSML|>
      - Du XML-like (balise_dsml, etc.)
    """
    if not text:
        return text
    original = text

    # 1) Supprimer les blocs complets <|DSML|>...<|/DSML|> (multi-lignes)
    text = re.sub(
        r'<\s*\|?\s*\|?\s*DSML\s*\|?\s*\|?\s*>.*?<\s*\|?\s*\/\s*\|?\s*DSML\s*\|?\s*\/?\s*\|?\s*>',
        '', text, flags=re.DOTALL | re.IGNORECASE
    )

    # 2) Supprimer toutes les lignes contenant encore 'DSML' (balises orphelines)
    lines = [l for l in text.split('\n') if 'DSML' not in l.upper()]
    text = '\n'.join(lines)

    # 3) Supprimer les balises résiduelles qui auraient survécu au filtre
    text = re.sub(r'<\s*\|?\s*\/?\s*\|?\s*DSML\s*\|?\s*\/?\s*\|?\s*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*\|\s*\|\s*\/?\s*DSML\s*\/?\s*\|\s*\|\s*>', '', text, flags=re.IGNORECASE)

    # 4) Supprimer les balises <think>...</think> (Qwen / DeepSeek)
    text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<think\s*/?>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</think\s*>', '', text, flags=re.IGNORECASE)

    # 5) Supprimer les blocs <tool_calls>...</tool_calls> (DeepSeek leak)
    text = re.sub(r'<tool_calls>[\s\S]*?</tool_calls>', '', text, flags=re.IGNORECASE | re.DOTALL)

    # 6) Supprimer les invocations d'outils orphelines
    text = re.sub(r'<invoke\s+name\s*=\s*"[^"]*"\s*>[\s\S]*?</invoke>', '', text, flags=re.IGNORECASE | re.DOTALL)

    # 7) Supprimer [Calling tool: ...] (DeepSeek V4 Flash leak)
    text = re.sub(r'\[Calling tool:\s*\w+\s*(?:with arguments:\s*\{[^}]*\})?\].*', '', text, flags=re.IGNORECASE)

    # 8) Supprimer <*:tool_call>...</*:tool_call> (MiniMax, DeepSeek, etc.)
    text = re.sub(r'<\w+:tool_call\s*>[\s\S]*?</\w+:tool_call\s*>', '', text, flags=re.IGNORECASE | re.DOTALL)

    # 9) Fallback : si le texte nettoyé est trop court (< 20 chars) alors que l'original
    #    est long, ne pas restaurer l'original — garder le nettoyé (évite de réintroduire des leaks)
    result = text.strip()
    if len(result) < 20 and len(original) > 50:
        # Simplement enlever les balises résiduelles, ne pas restaurer l'original
        result = re.sub(r'<[^>]+>', '', result).strip()
    return result or text.strip()
