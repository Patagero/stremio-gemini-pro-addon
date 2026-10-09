import logging
import asyncio
from typing import Optional, Dict, Tuple, List
import httpx
from . import config

logger = logging.getLogger("subtitle_fetcher")

# ISO 639-1 / 639-2 mappings
LANG_MAP = {
    "it": ["ita", "it"],
    "en": ["eng", "en"],
    "sl": ["slv", "sl"],
}


async def fetch_from_stremio_opensubtitles(
    imdb_id: str,
    target_lang: str,
    media_type: str = "movie"
) -> Optional[Dict]:
    """
    Fetch subtitles from official Stremio OpenSubtitles v3 addon (no auth required).
    """
    clean_id = imdb_id.replace("tt", "")
    url = f"https://opensubtitles-v3.strem.io/subtitles/{media_type}/tt{clean_id}.json"
    target_codes = LANG_MAP.get(target_lang, [target_lang])

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return None

            data = r.json()
            subtitles = data.get("subtitles", [])

            # Filter matching language tracks
            matched = [s for s in subtitles if s.get("lang") in target_codes]
            if not matched:
                return None

            # Download the first matching subtitle file
            sub_entry = matched[0]
            dl_url = sub_entry.get("url")
            if not dl_url:
                return None

            dl_res = await client.get(dl_url, headers={"User-Agent": "Mozilla/5.0"})
            if dl_res.status_code == 200 and dl_res.text.strip():
                return {
                    "srt": dl_res.text,
                    "language": target_lang,
                    "fileName": f"{imdb_id}.{target_lang}.srt",
                    "source": "stremio-opensubtitles-v3"
                }
    except Exception as e:
        logger.warning(f"Stremio OpenSubtitles error for {imdb_id} ({target_lang}): {e}")

    return None


async def fetch_from_opensubtitles_api(
    imdb_id: str,
    target_lang: str,
    media_type: str = "movie"
) -> Optional[Dict]:
    """
    Fetch subtitle via OpenSubtitles.com API if OPENSUBTITLES_API_KEY is configured.
    """
    if not config.OPENSUBTITLES_API_KEY:
        return None

    clean_id = imdb_id.replace("tt", "").split(":")[0]
    headers = {
        "Api-Key": config.OPENSUBTITLES_API_KEY,
        "User-Agent": config.OPENSUBTITLES_USER_AGENT,
        "Accept": "*/*"
    }

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            search_res = await client.get(
                "https://api.opensubtitles.com/api/v1/subtitles",
                headers=headers,
                params={"imdb_id": clean_id, "languages": target_lang, "order_by": "downloads", "order_direction": "desc"}
            )
            if search_res.status_code != 200:
                return None

            items = search_res.json().get("data", [])
            if not items:
                return None

            file_id = items[0].get("attributes", {}).get("files", [{}])[0].get("file_id")
            if not file_id:
                return None

            dl_res = await client.post("https://api.opensubtitles.com/api/v1/download", headers=headers, json={"file_id": file_id})
            if dl_res.status_code != 200:
                return None

            link = dl_res.json().get("link")
            if not link:
                return None

            srt_res = await client.get(link)
            if srt_res.status_code == 200:
                return {
                    "srt": srt_res.text,
                    "language": target_lang,
                    "fileName": f"{imdb_id}.{target_lang}.srt",
                    "source": "opensubtitles-com-api"
                }
    except Exception as e:
        logger.warning(f"OpenSubtitles API error: {e}")

    return None


async def fetch_source_subtitle(
    imdb_id: str,
    preferred_lang: Optional[str] = None,
    media_type: str = "movie"
) -> Dict:
    """
    Fetch source subtitle following priority:
    1. Check if authentic Slovenian already exists (zero-cost pass-through)
    2. Preferred language (e.g. IT if specified)
    3. Fallback priority (1. IT -> 2. EN)
    """
    # 1. First check if native Slovenian exists
    slo_res = await fetch_from_stremio_opensubtitles(imdb_id, "sl", media_type)
    if not slo_res:
        slo_res = await fetch_from_opensubtitles_api(imdb_id, "sl", media_type)
    if slo_res:
        slo_res["isNativeSlovene"] = True
        logger.info(f"Native Slovenian subtitles found for {imdb_id} (zero AI cost)")
        return slo_res

    # 2. Build search chain
    search_langs = []
    if preferred_lang and preferred_lang in config.SUPPORTED_SOURCE_LANGUAGES:
        search_langs.append(preferred_lang)
    for l in config.SOURCE_LANGUAGE_PRIORITY:
        if l not in search_langs:
            search_langs.append(l)

    for lang in search_langs:
        # Try Stremio OpenSubtitles v3 first
        res = await fetch_from_stremio_opensubtitles(imdb_id, lang, media_type)
        if res:
            res["isNativeSlovene"] = False
            logger.info(f"Found {lang.upper()} subtitle for {imdb_id} via Stremio OpenSubtitles")
            return res

        # Try OpenSubtitles.com API if configured
        res = await fetch_from_opensubtitles_api(imdb_id, lang, media_type)
        if res:
            res["isNativeSlovene"] = False
            logger.info(f"Found {lang.upper()} subtitle for {imdb_id} via OpenSubtitles API")
            return res

    raise RuntimeError(f"No subtitle found for {imdb_id} in any of: {search_langs}")
