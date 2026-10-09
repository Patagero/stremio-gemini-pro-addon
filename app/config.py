import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# Port & Server
PORT = int(os.environ.get("PORT", "7004"))
HOST = os.environ.get("HOST", "0.0.0.0")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

# Google Gemini API
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash").strip()
GEMINI_FALLBACK_MODELS = [
    GEMINI_MODEL,
    "gemini-3.7-flash",
    "gemini-3.7-pro",
    "gemini-3.7-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
]

# Translation & Subtitling Settings
TARGET_CPS = int(os.environ.get("TARGET_CPS", "17"))
MAX_LINE_CHARS = int(os.environ.get("MAX_LINE_CHARS", "42"))
MAX_LINES = 2
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "50"))
TRANSLATION_CONCURRENCY = int(os.environ.get("TRANSLATION_CONCURRENCY", "4"))

# Source Language Priority (1. Italian -> 2. English)
SOURCE_LANGUAGE_PRIORITY = ["it", "en"]
SUPPORTED_SOURCE_LANGUAGES = ["it", "en"]

LANGUAGE_DISPLAY_NAMES = {
    "it": "ITALIJANŠČINA",
    "en": "ANGLEŠČINA",
}

# Subtitle Provider Options (OpenSubtitles)
OPENSUBTITLES_API_KEY = os.environ.get("OPENSUBTITLES_API_KEY", "").strip()
OPENSUBTITLES_USER_AGENT = os.environ.get("OPENSUBTITLES_USER_AGENT", "GeminiProSloAddon v1.0.0")
OPENSUBTITLES_USERNAME = os.environ.get("OPENSUBTITLES_USERNAME", "").strip()
OPENSUBTITLES_PASSWORD = os.environ.get("OPENSUBTITLES_PASSWORD", "").strip()

# TMDB API (Optional, Cinemeta fallback is always active)
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()

# Cache Directory
CACHE_DIR = Path(os.environ.get("CACHE_DIR", str(ROOT_DIR / ".cache")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_MS = int(os.environ.get("CACHE_TTL_MS", str(7 * 24 * 60 * 60 * 1000)))
