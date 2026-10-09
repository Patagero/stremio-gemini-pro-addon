import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import httpx
from . import config

logger = logging.getLogger("metadata")


@dataclass
class MovieMetadata:
    title: str = "Unknown"
    genres: List[str] = field(default_factory=list)
    plot: str = ""
    cast: List[Dict] = field(default_factory=list)
    imdb_id: str = ""
    year: str = ""

    @property
    def genre_string(self) -> str:
        return ", ".join(self.genres) if self.genres else "General"

    @property
    def cast_string(self) -> str:
        if not self.cast:
            return "No cast metadata available."
        lines = []
        for c in self.cast[:15]:
            name = c.get("name", "")
            char = c.get("character", "")
            gender = c.get("gender", "unknown")
            if char:
                lines.append(f"{char} ({name}): {gender}")
            else:
                lines.append(f"{name}: {gender}")
        return "\n".join(lines)


async def fetch_cinemeta_metadata(imdb_id: str, media_type: str = "movie") -> Optional[MovieMetadata]:
    clean_id = imdb_id.replace("tt", "")
    url = f"https://v3-cinemeta.strem.io/meta/{media_type}/tt{clean_id}.json"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return None
            data = r.json().get("meta", {})
            if not data:
                return None

            genres = data.get("genres", [])
            cast_list = []
            for c in data.get("cast", [])[:15]:
                if isinstance(c, dict):
                    cast_list.append({
                        "name": c.get("name", ""),
                        "character": c.get("role", c.get("character", "")),
                        "gender": "unknown"
                    })
                else:
                    cast_list.append({
                        "name": str(c),
                        "character": "",
                        "gender": "unknown"
                    })

            return MovieMetadata(
                title=data.get("name", data.get("title", "Unknown")),
                genres=genres,
                plot=data.get("description", data.get("overview", "")),
                cast=cast_list,
                imdb_id=f"tt{clean_id}",
                year=str(data.get("year", ""))
            )
    except Exception as e:
        logger.warning(f"Cinemeta fetch error for {imdb_id}: {e}")
        return None


async def fetch_tmdb_metadata(imdb_id: str) -> Optional[MovieMetadata]:
    if not config.TMDB_API_KEY:
        return None
    try:
        base = "https://api.themoviedb.org/3"
        async with httpx.AsyncClient(timeout=10) as client:
            find_res = await client.get(
                f"{base}/find/{imdb_id}",
                params={"api_key": config.TMDB_API_KEY, "language": "en-US", "external_source": "imdb_id"}
            )
            find_data = find_res.json()
            item = (find_data.get("movie_results") or [None])[0] or (find_data.get("tv_results") or [None])[0]
            if not item:
                return None

            media_type = "movie" if find_data.get("movie_results") else "tv"
            details_res = await client.get(
                f"{base}/{media_type}/{item['id']}",
                params={"api_key": config.TMDB_API_KEY, "language": "en-US", "append_to_response": "credits"}
            )
            details = details_res.json()

            gender_map = {1: "female", 2: "male", 3: "non-binary"}
            cast_list = []
            for c in (details.get("credits", {}).get("cast") or [])[:15]:
                cast_list.append({
                    "name": c.get("name", ""),
                    "character": c.get("character", ""),
                    "gender": gender_map.get(c.get("gender"), "unknown")
                })

            return MovieMetadata(
                title=details.get("title") or details.get("name") or imdb_id,
                genres=[g["name"] for g in details.get("genres", [])],
                plot=details.get("overview", ""),
                cast=cast_list,
                imdb_id=imdb_id,
                year=str(details.get("release_date") or details.get("first_air_date") or "")[:4]
            )
    except Exception as e:
        logger.warning(f"TMDB fetch error for {imdb_id}: {e}")
        return None


async def get_metadata(imdb_id: str, media_type: str = "movie") -> MovieMetadata:
    # 1. Try TMDB if configured (has exact character genders)
    if config.TMDB_API_KEY:
        meta = await fetch_tmdb_metadata(imdb_id)
        if meta and meta.genres:
            return meta

    # 2. Try Cinemeta (fast, built-in)
    meta = await fetch_cinemeta_metadata(imdb_id, media_type)
    if meta and meta.genres:
        return meta

    return MovieMetadata(title=imdb_id, imdb_id=imdb_id)


def get_genre_translation_rules(genres: List[str]) -> str:
    """Return tailored translation rules for tone, slang, and terminology based on movie genres."""
    genre_lower = [g.lower() for g in genres]
    rules = []

    if any(g in genre_lower for g in ["sci-fi", "science fiction", "znanstvena fantastika"]):
        rules.append(
            "Znanstvena fantastika (Sci-Fi): Uporabljaj uveljavljeno slovensko terminologijo "
            "(nadsvetlobni pogon, ščiti, senzorji, teleportacija, hiper-skok, umetna inteligenca, kvantni). "
            "Strokovni izrazi naj bodo dosledni in naravni."
        )

    if any(g in genre_lower for g in ["action", "akcija", "crime", "kriminalka", "thriller", "triler"]):
        rules.append(
            "Akcija / Kriminalka / Triler: Uporabljaj surov, naraven filmski pogovorni jezik, "
            "ulični sleng in pristne slovenske kletvice (\"fak\", \"daj no\", \"stari\", \"mater\", "
            "\"k vragu\", \"kaj dogaja\", \"gremo\"). Brez zastarelih ali prisiljenih knjižnih izrazov."
        )

    if any(g in genre_lower for g in ["comedy", "komedija"]):
        rules.append(
            "Komedija: Živahni, duhoviti in naravni slovenski idiomi ter situacijske šale. "
            "Ne prevajaj tujih šal dobesedno, ampak jih prilagodi slovenskemu duhu."
        )

    if any(g in genre_lower for g in ["horror", "grozljivka", "terror"]):
        rules.append(
            "Grozljivka / Horror: Ohrani napeto, mrzlo atmosfero. Uporabljaj izraze, "
            "ki gradijo strah in negotovost (\"kaj je to?\", \"slišiš to?\", \"ne hodi tja\")."
        )

    if any(g in genre_lower for g in ["romance", "romantična", "ljubezen"]):
        rules.append(
            "Romantična: Topel, čustven jezik z naravnimi izrazi naklonjenosti. "
            "Pazljivo z vikanjem/tikanjem glede na odnos likov."
        )

    if any(g in genre_lower for g in ["animation", "animacija", "family", "družina"]):
        rules.append(
            "Animacija / Družinski: Prijazen, igriv in naraven slovenski jezik, "
            "prilagojen celotni družini. Preprosto in razumljivo."
        )

    if any(g in genre_lower for g in ["drama", "zgodovinski", "history", "historical"]):
        rules.append(
            "Drama / Zgodovinski: Rahlo uglajenejši jezik z doslednim vikanjem med uradnimi osebami in gospodo."
        )

    if not rules:
        rules.append(
            "Splošno: Uporabljaj naravno, tekočo pogovorno slovenščino. Brez dobesednih ali robotskih prevodov."
        )

    return "\n".join(f"- {r}" for r in rules)
