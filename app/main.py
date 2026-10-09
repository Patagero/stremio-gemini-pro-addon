import os
import sys
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .srt_engine import parse_srt, to_srt, remove_sdh, reconcile_srt, prepend_notice_cue
from .metadata import get_metadata
from .gemini_client import GeminiProTranslator
from .subtitle_fetcher import fetch_source_subtitle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("stremio_gemini_pro")

app = FastAPI(title="Slo AI Subtitle Translator (Gemini 3.7 Pro)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory caches & active job tracking
memory_cache: Dict[str, str] = {}
active_jobs: Dict[str, asyncio.Task] = {}

MANIFEST = {
    "id": "com.stremio.gemini37pro.slo.translator",
    "version": "1.0.0",
    "name": "Slo AI Gemini 3.7 Pro Prevajalnik",
    "description": "Vrhunski slovenski filmski podnapisi z Gemini 3.7 Pro: samodejna izbira vira (IT -> ENG), natančno SDH čiščenje, spolno ujemanje (ona/on) in žanrska prilagoditev.",
    "resources": ["subtitles"],
    "types": ["movie", "series"],
    "idPrefixes": ["tt"],
    "catalogs": [],
    "behaviorHints": {
        "configurable": True,
        "configurationRequired": False,
    },
}


def sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)


def get_cached_disk_srt(imdb_id: str, lang: str) -> Optional[str]:
    safe_name = sanitize_filename(f"{imdb_id}_{lang}") + ".sl.srt"
    file_path = config.CACHE_DIR / safe_name
    if file_path.exists():
        try:
            return file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Error reading disk cache {safe_name}: {e}")
    return None


def save_cached_disk_srt(imdb_id: str, lang: str, content: str):
    safe_name = sanitize_filename(f"{imdb_id}_{lang}") + ".sl.srt"
    file_path = config.CACHE_DIR / safe_name
    try:
        file_path.write_text(content, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Error saving to disk cache {safe_name}: {e}")


def get_notice_message(source_lang: str) -> str:
    if source_lang == "it":
        return "Prevod iz italijanskih podnapisov (Gemini 3.7 Pro)."
    elif source_lang == "en":
        return "Prevod iz angleških podnapisov (Gemini 3.7 Pro)."
    return f"Prevod iz {source_lang.upper()} podnapisov (Gemini 3.7 Pro)."


async def perform_translation_pipeline(imdb_id: str, lang: str = "auto", media_type: str = "movie") -> str:
    cache_key = f"{imdb_id}:{lang}"

    # 1. Check disk / memory cache
    cached = memory_cache.get(cache_key) or get_cached_disk_srt(imdb_id, lang)
    if not cached and lang == "auto":
        # Also check if it was cached under specific language
        cached = memory_cache.get(f"{imdb_id}:it") or get_cached_disk_srt(imdb_id, "it") or \
                 memory_cache.get(f"{imdb_id}:en") or get_cached_disk_srt(imdb_id, "en") or \
                 memory_cache.get(f"{imdb_id}:sl") or get_cached_disk_srt(imdb_id, "sl")
    if cached:
        notice = "Naloženi že prej prevedeni slovenski podnapisi."
        logger.info(f"[{imdb_id}] Serving from cache with notice")
        return prepend_notice_cue(cached, notice)

    logger.info(f"[{imdb_id}] Starting translation pipeline (source preference: {lang.upper()})")

    # 2. Fetch source subtitle (Auto checks: Native Slovene -> Italian -> English)
    pref_lang = None if lang == "auto" else lang
    source_data = await fetch_source_subtitle(imdb_id, preferred_lang=pref_lang, media_type=media_type)
    raw_srt = source_data.get("srt", "")
    used_lang = source_data.get("language", "en")
    is_native = source_data.get("isNativeSlovene", False)

    if not raw_srt.strip():
        raise RuntimeError(f"Source subtitle for {imdb_id} is empty")

    # 3. Clean SDH
    cleaned_srt = remove_sdh(raw_srt)
    source_cues = parse_srt(cleaned_srt)

    if not source_cues:
        raise RuntimeError(f"SDH cleanup resulted in 0 cues for {imdb_id}")

    # If already native Slovenian, skip AI translation
    if is_native:
        notice = "Najdeni slovenski podnapisi-prevod ni potreben."
        final_srt = prepend_notice_cue(cleaned_srt, notice)
        memory_cache[cache_key] = cleaned_srt
        save_cached_disk_srt(imdb_id, lang, cleaned_srt)
        save_cached_disk_srt(imdb_id, "auto", cleaned_srt)
        return final_srt

    # 4. Fetch IMDb / Cinemeta / TMDB Metadata
    meta = await get_metadata(imdb_id, media_type)
    logger.info(f"[{imdb_id}] Metadata loaded: {meta.title} | Genres: {meta.genre_string}")

    # 5. Gemini 3.7 Translation
    translator = GeminiProTranslator()
    translated_map = await translator.translate_all(source_cues, meta)

    # 6. Reconcile & Build SRT
    reconciled_cues = reconcile_srt(source_cues, translated_map)
    final_translated_srt = to_srt(reconciled_cues)

    # 7. Persist to cache
    memory_cache[cache_key] = final_translated_srt
    save_cached_disk_srt(imdb_id, lang, final_translated_srt)
    save_cached_disk_srt(imdb_id, "auto", final_translated_srt)
    save_cached_disk_srt(imdb_id, used_lang, final_translated_srt)

    notice = get_notice_message(used_lang)
    logger.info(f"[{imdb_id}] Translation complete ({len(reconciled_cues)} cues). Saved to cache.")
    return prepend_notice_cue(final_translated_srt, notice)


# ── Routes ─────────────────────────────────────────────────────────────

@app.get("/manifest.json")
@app.get("/manifest")
async def manifest():
    return JSONResponse(MANIFEST)


@app.get("/health")
async def health():
    return JSONResponse({
        "status": "healthy",
        "geminiConfigured": bool(config.GEMINI_API_KEY),
        "geminiModel": config.GEMINI_MODEL,
        "concurrency": config.TRANSLATION_CONCURRENCY,
        "chunkSize": config.CHUNK_SIZE,
        "targetCps": config.TARGET_CPS,
        "maxLineChars": config.MAX_LINE_CHARS,
        "tmdbConfigured": bool(config.TMDB_API_KEY),
        "openSubtitlesConfigured": bool(config.OPENSUBTITLES_API_KEY),
        "activeJobs": len(active_jobs),
        "memoryCacheEntries": len(memory_cache),
        "cacheDir": str(config.CACHE_DIR),
    })


@app.get("/configure")
async def configure():
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Slo AI Gemini 3.7 Pro Translator</title></head>
    <body style="font-family:sans-serif;max-width:600px;margin:40px auto;line-height:1.6;color:#333;">
        <h2>Slo AI Gemini 3.7 Pro Prevajalnik</h2>
        <p>Vrhunski slovenski podnapisi z uporabo modela Google Gemini 3.7 Pro.</p>
        <p>Prioriteta vira: <b>Italijanščina (IT) &rarr; Angleščina (ANG)</b>.</p>
        <p>Za namestitev v Stremio uporabite URL: <code>/manifest.json</code></p>
    </body>
    </html>
    """
    return Response(content=html, media_type="text/html")


def get_public_root(request: Request) -> str:
    if config.PUBLIC_BASE_URL:
        return config.PUBLIC_BASE_URL.rstrip("/")
    
    # Auto-resolve from reverse proxy headers (Render, Cloudflare, etc.)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or f"{request.url.hostname}:{request.url.port}"
    proto = request.headers.get("x-forwarded-proto") or ("https" if "onrender.com" in host or "herokuapp.com" in host else request.url.scheme)
    return f"{proto}://{host}"


@app.get("/subtitles/{media_type}/{imdb_id}")
@app.get("/subtitles/{media_type}/{imdb_id}.json")
@app.get("/subtitles/{media_type}/{imdb_id}/{extra:path}")
async def get_subtitles_route(
    media_type: str,
    imdb_id: str,
    request: Request,
    extra: str = ""
):
    clean_id = imdb_id.replace(".json", "")
    root = get_public_root(request)
    logger.info(f"[{clean_id}] Subtitles requested. Returning subtitle url: {root}/subtitle-file/{clean_id}/auto.srt")

    # Single clean auto-detected Slovenian track
    subtitles = [
        {
            "id": f"gemini-pro-{media_type}-{clean_id}",
            "url": f"{root}/subtitle-file/{clean_id}/auto.srt",
            "lang": "slv",
            "label": "Slovenski AI prevod (Gemini 3.7)"
        }
    ]

    return JSONResponse({"subtitles": subtitles})


@app.get("/subtitle-file/{imdb_id}/{lang}.srt")
@app.get("/subtitle-file/{imdb_id}.srt")
async def serve_subtitle_file(imdb_id: str, lang: str = "auto", request: Request = None):
    clean_id = imdb_id.replace(".json", "").replace(".sl", "")
    cache_key = f"{clean_id}:{lang}"

    # 1. Check if already translated and available in cache
    cached = memory_cache.get(cache_key) or get_cached_disk_srt(clean_id, lang) or \
             memory_cache.get(f"{clean_id}:auto") or get_cached_disk_srt(clean_id, "auto")
    if cached:
        notice = "Naloženi že prej prevedeni slovenski podnapisi."
        srt_content = prepend_notice_cue(cached, notice)
        return PlainTextResponse(srt_content, media_type="application/x-subrip; charset=utf-8")

    # 2. Deduplicate inflight tasks
    if clean_id not in active_jobs or active_jobs[clean_id].done():
        active_jobs[clean_id] = asyncio.create_task(perform_translation_pipeline(clean_id, lang))

    task = active_jobs[clean_id]

    # 3. Wait up to 10 seconds for translation
    try:
        done, _ = await asyncio.wait([task], timeout=10.0)
        if task in done:
            srt_result = task.result()
            return PlainTextResponse(srt_result, media_type="application/x-subrip; charset=utf-8")
        else:
            # Translation still in progress — return immediate friendly notice cue
            logger.info(f"[{clean_id}] Translation taking longer than 10s, returning in-progress cue")
            progress_cue = (
                "0\n00:00:01,000 --> 00:00:08,000\n"
                "[Slo AI: Prevajam celoten film v ozadju... Osveži podnapise čez nekaj sekund]\n"
            )
            return PlainTextResponse(progress_cue, media_type="application/x-subrip; charset=utf-8")
    except Exception as e:
        logger.error(f"[{clean_id}] Translation error: {e}")
        error_cue = f"0\n00:00:01,000 --> 00:00:06,000\n[Napaka: {str(e)[:150]}]\n"
        return PlainTextResponse(error_cue, media_type="application/x-subrip; charset=utf-8", status_code=503)


def main():
    import uvicorn
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
