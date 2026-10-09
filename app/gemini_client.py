import json
import re
import logging
import asyncio
from typing import List, Dict, Optional, Tuple
import httpx
from . import config
from .srt_engine import Cue, cue_duration_seconds, max_chars_for_duration
from .metadata import MovieMetadata, get_genre_translation_rules

logger = logging.getLogger("gemini")


class GeminiProTranslator:
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model = model or config.GEMINI_MODEL
        self.fallback_models = config.GEMINI_FALLBACK_MODELS

    async def _call_gemini_raw(self, system_prompt: str, user_text: str, model: str = None) -> str:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        models_to_try = [model] if model else self.fallback_models
        last_error = None

        async with httpx.AsyncClient(timeout=120) as client:
            for current_model in models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={self.api_key}"
                body = {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": f"{system_prompt}\n\n---\n\n{user_text}"}]
                        }
                    ],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.2
                    }
                }

                try:
                    r = await client.post(url, json=body)
                    if r.status_code == 200:
                        data = r.json()
                        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        return "".join(p.get("text", "") for p in parts).strip()

                    error_msg = r.text[:300]
                    last_error = RuntimeError(f"Gemini HTTP {r.status_code} ({current_model}): {error_msg}")
                    if r.status_code in (404, 400):
                        logger.warning(f"Gemini model {current_model} returned {r.status_code}, trying fallback...")
                        continue
                    if r.status_code in (429, 503):
                        logger.warning(f"Gemini rate limit / high load on {current_model}, retrying with fallback...")
                        await asyncio.sleep(2)
                        continue
                    raise last_error

                except httpx.TimeoutException:
                    last_error = RuntimeError(f"Timeout on {current_model}")
                    logger.warning(f"Timeout on {current_model}, trying fallback...")
                    continue
                except Exception as e:
                    last_error = e
                    logger.warning(f"Error on {current_model}: {e}")
                    continue

        raise last_error or RuntimeError("Gemini API call failed")

    def _parse_translations_json(self, response_text: str) -> Dict[str, str]:
        """Parse structured translation response robustly."""
        # 1. Direct JSON parse
        try:
            raw = response_text.strip()
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start:end + 1]
            data = json.loads(raw)
            translations = data.get("translations", data if isinstance(data, list) else [])
            result = {}
            for item in translations:
                item_id = str(item.get("id", "")).strip()
                text = str(item.get("text", "")).strip()
                if item_id and text:
                    result[item_id] = text
            if result:
                return result
        except Exception:
            pass

        # 2. Loose regex extraction
        result = {}
        pattern = re.compile(r'"id"\s*:\s*"?([^"\n,}]+)"?\s*,\s*"text"\s*:\s*"((?:\\.|[^"\\])*)"')
        for match in pattern.finditer(response_text):
            item_id = match.group(1).strip()
            try:
                text = json.loads(f'"{match.group(2)}"')
            except Exception:
                text = match.group(2).replace('\\"', '"').replace("\\n", "\n")
            text = text.strip()
            if item_id and text:
                result[item_id] = text

        return result

    def _build_system_prompt(self, meta: MovieMetadata) -> str:
        genre_rules = get_genre_translation_rules(meta.genres)
        return f"""You are an elite, award-winning film subtitle translator specializing in translating movie and series subtitles into natural, idiomatic Slovenian using Gemini 3.7 Pro.

FILM CONTEXT:
Title: {meta.title}
Genres: {meta.genre_string}
Plot: {meta.plot or 'Not provided'}
Cast & Identified Genders:
{meta.cast_string}

GENRE-ADAPTED RULES & TONE:
{genre_rules}

CORE TRANSLATION & SUBTITLING RULES:

1. SPOLNO UJEMANJE (ONA / ON) — KRITIČNO:
- Dosledno uporabljaj določen spol likov iz zgornje tabele.
- Ženske oblike: "rekla sem", "prišla sem", "bila sem", "vesela sem", "si videla?", "si pripravljena?".
- Moške oblike: "rekel sem", "prišel sem", "bil sem", "vesel sem", "si videl?", "si pripravljen?".
- V italijanščini izkoristi spolne končnice izvirnika ("sono andata" -> "šla sem", "ero stanco" -> "bil sem utrujen").
- Pravilno uporabljaj slovensko dvojino (npr. "greva", "bova videla/videli", "morava").

2. OMEJITEV VRSTIC IN HITROST BRANJA (MAX 2 VRSTICI):
- Vsak posamezen podnapis (cue) mora biti razdeljen na NAJVEČ DVE KRATKI VRSTICI (max {config.MAX_LINE_CHARS} znakov na vrstico).
- Za udobno branje na TV zaslonu se drži hitrosti {config.TARGET_CPS} znakov na sekundo glede na čas trajanja.
- Strni predolgo besedilo: izpusti odvečna mašila in ponavljanja, ohrani bistvo in ton dialoga.

3. NARAVEN POGOVORNI JEZIK:
- Uporabljaj naravno, tekočo pogovorno slovenščino. Brez dobesednih ali robotskih prevodov.
- Ohrani dosledno tikanje ali vikanje glede na odnose med liki.

4. POPOLNA TEHNIČNA INTEGRITETA SRT:
- Ohraniti moraš točne ID številke vseh podnapisov.
- Izhod vrni IZKLJUČNO kot JSON v obliki: {{"translations":[{{"id":"1","text":"Prva vrstica\\nDruga vrstica"}}]}}"""

    def _build_user_prompt(self, cues: List[Cue]) -> str:
        lines = []
        for cue in cues:
            duration = cue_duration_seconds(cue)
            budget = max_chars_for_duration(duration, config.TARGET_CPS, config.MAX_LINE_CHARS, config.MAX_LINES)
            flat_text = cue.text.replace("\n", " / ")
            lines.append(f"[id={cue.id} duration={duration:.1f}s max_chars={budget}] {flat_text}")

        return (
            "Prevedi vsak cue v naravno slovenščino (max 2 vrstici na cue, upoštevaj spol likov). "
            'Vrni JSON: {"translations": [{"id": "...", "text": "..."}]}\n\n'
            f"SOURCE CUES:\n" + "\n".join(lines)
        )

    async def translate_chunk(self, chunk: List[Cue], meta: MovieMetadata) -> Dict[str, str]:
        system_prompt = self._build_system_prompt(meta)
        user_prompt = self._build_user_prompt(chunk)

        response = await self._call_gemini_raw(system_prompt, user_prompt)
        translated_map = self._parse_translations_json(response)

        # Self-repair pass if cues are missing
        if len(translated_map) < len(chunk):
            missing_ids = [c.id for c in chunk if c.id not in translated_map]
            logger.warning(f"Chunk incomplete ({len(translated_map)}/{len(chunk)}), repairing missing IDs: {missing_ids}")
            repair_prompt = f"{user_prompt}\n\nREPAIR: Missing cue IDs {missing_ids}. Return all cues in JSON."
            try:
                repair_res = await self._call_gemini_raw(system_prompt, repair_prompt)
                repaired_map = self._parse_translations_json(repair_res)
                translated_map.update(repaired_map)
            except Exception as e:
                logger.warning(f"Repair pass failed: {e}")

        return translated_map

    async def translate_all(self, cues: List[Cue], meta: MovieMetadata) -> Dict[str, str]:
        if not cues:
            return {}

        chunk_size = config.CHUNK_SIZE
        chunks = [cues[i:i + chunk_size] for i in range(0, len(cues), chunk_size)]
        logger.info(f"Translating {len(cues)} cues in {len(chunks)} chunks with concurrency={config.TRANSLATION_CONCURRENCY}")

        results_map = {}
        semaphore = asyncio.Semaphore(config.TRANSLATION_CONCURRENCY)

        async def worker(idx: int, ch: List[Cue]):
            async with semaphore:
                for attempt in range(1, 4):
                    try:
                        res = await self.translate_chunk(ch, meta)
                        logger.info(f"Chunk {idx + 1}/{len(chunks)} done ({len(res)}/{len(ch)} cues)")
                        return res
                    except Exception as e:
                        logger.warning(f"Chunk {idx + 1} attempt {attempt}/3 failed: {e}")
                        if attempt == 3:
                            return {}
                        await asyncio.sleep(2 * attempt)
                return {}

        tasks = [worker(i, ch) for i, ch in enumerate(chunks)]
        chunk_results = await asyncio.gather(*tasks)

        for res in chunk_results:
            results_map.update(res)

        return results_map
