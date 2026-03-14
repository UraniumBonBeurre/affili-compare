"""
settings.py — Variables centrales du projet MyGoodPick (affili-compare)
========================================================================
Importé par tous les scripts. Charge .env.local et expose les constantes.
"""

import os
from pathlib import Path

# ── Chargement .env.local ─────────────────────────────────────────────────────
ROOT = Path(__file__).parent
for _env in (ROOT / ".env.local", ROOT / ".env"):
    if _env.exists():
        for _line in _env.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

# ══════════════════════════════════════════════════════════════════════════════
# VARIABLES CENTRALES (configurables)
# ══════════════════════════════════════════════════════════════════════════════

production_workflow: bool = False      # False = sauvegarde locale, True = publication réelle
top_articles_per_day: int = 2          # Nombre d'articles générés par jour
nb_products_per_article: int = 5       # Nombre de produits par article
nb_pins_per_article: int = 2           # Nombre de pins Pinterest par article

# ── Modèles LLM / IA ─────────────────────────────────────────────────────────
CLASSIFICATION_LLM: str = "gemini-3.1-flash-lite-preview"
ARTICLES_WRITING_LLM: str = "deepseek-v3.2:cloud"
PINS_WRITING_LLM: str = "deepseek-v3.2:cloud"
VISUAL_GENERATOR_MODEL: str = "FLUX.1-schnell"

# ══════════════════════════════════════════════════════════════════════════════
# CREDENTIALS (depuis .env.local)
# ══════════════════════════════════════════════════════════════════════════════

# Supabase
SUPABASE_URL: str = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# Awin
AWIN_API_TOKEN: str = os.environ.get("AWIN_API_TOKEN", "")
AWIN_PUBLISHER_ID: str = os.environ.get("AWIN_PUBLISHER_ID", "")
AWIN_PRODUCTDATA_KEY: str = os.environ.get("AWIN_PRODUCTDATA_KEY", "") or AWIN_API_TOKEN
AWIN_FEED_ID_RDC: str = os.environ.get("AWIN_FEED_ID_RDC", "")

# Google AI (classification)
GOOGLE_AI_API_KEY: str = os.environ.get("GOOGLE_AI_API_KEY", "")
GOOGLE_AI_MODEL: str = CLASSIFICATION_LLM

# Ollama Cloud (articles + pins text)
OLLAMA_CLOUD_API_KEY: str = os.environ.get("OLLAMA_CLOUD_API_KEY", "")
OLLAMA_CLOUD_HOST: str = "https://api.ollama.com"
OLLAMA_CLOUD_MODEL: str = ARTICLES_WRITING_LLM
OLLAMA_CLOUD_PINS_MODEL: str = os.environ.get("OLLAMA_CLOUD_PINS_MODEL", PINS_WRITING_LLM)

# HuggingFace (image generation)
HF_API_TOKEN: str = os.environ.get("HF_API_TOKEN", "") or os.environ.get("HF_TOKEN", "")

# Pinterest
PINTEREST_ACCESS_TOKEN: str = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
PINTEREST_API_BASE: str = os.environ.get("PINTEREST_API_BASE", "https://api.pinterest.com/v5").rstrip("/")
PINTEREST_BOARD_ID: str = os.environ.get("PINTEREST_BOARD_ID", "")

# Cloudflare R2
R2_ACCOUNT_ID: str = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID: str = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY: str = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME: str = os.environ.get("R2_BUCKET_NAME", "")
R2_PUBLIC_URL: str = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")

# Site
SITE_URL: str = "https://mygoodpick.com"

# ══════════════════════════════════════════════════════════════════════════════
# CHEMINS
# ══════════════════════════════════════════════════════════════════════════════

TAXONOMY_PATH = ROOT / "config" / "taxonomy" / "product_types.json"
MERCHANT_CATEGORIES_PATH = ROOT / "src" / "config" / "merchant_categories.json"
BOARDS_PATH = ROOT / "data" / "pinterest_boards.json"
CACHE_DIR = ROOT / ".cache"
OUTPUT_DIR = ROOT / "output" / "top_pins"
LOCAL_PINTEREST_DIR = ROOT / "local_pinterest"

# Fonts: dossier local avec auto-création
FONTS_DIR = ROOT / "assets" / "fonts"
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS COMMUNS
# ══════════════════════════════════════════════════════════════════════════════

def sb_headers(extra: dict = None) -> dict:
    """Headers standard pour les appels REST Supabase."""
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def check_supabase():
    """Vérifie que les credentials Supabase sont présents."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        import sys
        print("❌  NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY requis dans .env.local")
        sys.exit(1)


def get_board_for_niche(niche: str, lang: str) -> tuple[str, str]:
    """Retourne (board_name, board_id) pour une niche et une langue ('fr' ou 'en').
    Charge data/pinterest_boards.json. Retourne ('', '') si non trouvé ou ID vide.
    """
    if not BOARDS_PATH.exists():
        return "", ""
    import json as _j
    try:
        boards = _j.loads(BOARDS_PATH.read_text(encoding="utf-8")).get("boards", [])
    except Exception:
        return "", ""
    for board in boards:
        if niche in board.get("niches", []):
            b = board.get(lang, {})
            return b.get("name", ""), b.get("board_id", "")
    return "", ""
