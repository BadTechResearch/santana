import os, sqlite3, logging, glob, requests
from core.db import get_db
from core.utils import get_base_dir

BASE_DIR = get_base_dir()
DB_PATH = os.path.join(BASE_DIR, "memory.db")

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        content TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        trigger_condition TEXT,
        steps TEXT,
        pitfalls TEXT,
        verification TEXT,
        usage_count INTEGER DEFAULT 1,
        success_rate REAL DEFAULT 1.0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()

def save_message(role: str, content: str):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO memory (role, content) VALUES (?, ?)", (role, content))
        conn.commit()
    except Exception as e:
        logging.error(f"save_message error: {e}")

def get_recent_memory(limit=60) -> list:
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT role, content FROM memory ORDER BY id DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]
    except Exception as e:
        logging.error(f"[MEMORY] get_recent_memory error: {e}")
        return []

def rotate_memory(max_souvenirs=500):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM memory")
        total = cur.fetchone()[0]
        if total > max_souvenirs:
            overflow = total - max_souvenirs
            # Batch DELETE : une seule requête au lieu de N
            cur.execute(
                "DELETE FROM memory WHERE id IN ("
                "SELECT id FROM memory ORDER BY timestamp ASC LIMIT ?"
                ")", (overflow,)
            )
            conn.commit()
            logging.info(f"[MEMORY] Rotation: {overflow} anciens supprimes en batch, {max_souvenirs} conserves")
    except Exception as e:
        logging.error(f"[MEMORY] Erreur rotation: {e}")

def count_memory() -> int:
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM memory")
        count = c.fetchone()[0]
        return count
    except Exception as e:
        logging.error(f"[MEMORY] count_memory error: {e}")
        return 0

def seed_initial_skills():
    """Sync skills/ .md files vers la DB au démarrage."""
    import glob
    skills_dir = os.path.join(BASE_DIR, "skills")
    os.makedirs(skills_dir, exist_ok=True)
    try:
        conn = get_db()
        c = conn.cursor()
        for md in glob.glob(os.path.join(skills_dir, "*.md")):
            title = os.path.basename(md).replace(".md", "").replace("_", " ").title()
            content = open(md, "r").read()
            c.execute("SELECT COUNT(*) FROM skills WHERE title=?", (title,))
            if c.fetchone()[0] == 0:
                c.execute("INSERT INTO skills (title, trigger_condition, steps, pitfalls, verification) VALUES (?,?,?,?,?)",
                    (title, "auto", content[:500], "", ""))
            else:
                c.execute("UPDATE skills SET steps=?, updated_at=CURRENT_TIMESTAMP WHERE title=?",
                    (content[:500], title))
        conn.commit()
    except Exception as e:
        logging.error(f"[MEMORY] seed_initial_skills error: {e}")


def count_skills() -> int:
    """Retourne le nombre de skills en base."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM skills")
        count = c.fetchone()[0]
        return count
    except Exception as e:
        logging.error(f"[MEMORY] count_skills error: {e}")
        return 0


def clear_short_term():
    """Vide la mémoire conversationnelle (table memory)."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM memory")
        conn.commit()
        logging.info("[MEMORY] Table memory vidée par /reset")
    except Exception as e:
        logging.error(f"[MEMORY] clear_short_term error: {e}")


def get_top_skills(limit=5) -> list:
    """Retourne les N skills les plus utilisées."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT title, steps, usage_count FROM skills ORDER BY usage_count DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        return rows
    except Exception as e:
        logging.error(f"[MEMORY] get_top_skills error: {e}")
        return []
