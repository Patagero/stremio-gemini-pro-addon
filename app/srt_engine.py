import re
from dataclasses import dataclass
from typing import List, Optional

TIMING_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})"
)

# SDH stripping regex patterns
SDH_BRACKET_RE = re.compile(r"\[[^\]\n]*\]")
SDH_PAREN_RE = re.compile(
    r"\([^)\n]*(?:laughter|giggle|gasp|sobbing|crying|music|sigh|groan|"
    r"screaming|screams|whisper|whispering|cough|applause|cheering|cheer|"
    r"chuckle|snicker|breathing|grunts|grunt|engine|radio|phone|ringing|"
    r"glass|shattering|thud|crash|explosion|gunfire|shot|"
    r"alarm|beep|buzz|knock|door|footsteps|wind|rain|thunder|"
    r"people|crowd|audience|sirens|horn|roar|growl|howl|panting|"
    r"moan|groan|slam|clank|rattle|scrape|sizzle|fizz|"
    r"sob|giggle|laugh|cry|gasp|pant|shout|yell)[^)\n]*\)",
    re.IGNORECASE,
)
SDH_ASTERISK_RE = re.compile(r"\*[^*]*\*")
SDH_MUSIC_RE = re.compile(r"[♪♫][^♪♫\n]*[♪♫]?")
SDH_SPEAKER_RE = re.compile(r"^[-\s]*[A-ZČŠŽĐĆ0-9 .'\-]{2,30}:\s*")


@dataclass
class Cue:
    id: str
    start: str
    end: str
    text: str

    @property
    def timecode(self) -> str:
        return f"{self.start} --> {self.end}"


def parse_srt(srt_text: str) -> List[Cue]:
    """Parse raw SRT string into list of Cue objects."""
    text = (srt_text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    cues: List[Cue] = []

    for block in blocks:
        lines = block.split("\n")
        if not lines:
            continue

        idx = 0
        cue_id = lines[0].strip()
        if cue_id.isdigit():
            idx = 1
        else:
            cue_id = str(len(cues) + 1)

        timing_line = lines[idx] if idx < len(lines) else ""
        m = TIMING_RE.search(timing_line)
        if not m:
            continue

        start = m.group(1).replace(".", ",")
        end = m.group(2).replace(".", ",")
        text_lines = lines[idx + 1:]
        cue_text = "\n".join(text_lines).strip()

        cues.append(Cue(id=cue_id, start=start, end=end, text=cue_text))

    return cues


def to_srt(cues: List[Cue]) -> str:
    """Format list of Cue objects into standard SRT string."""
    return "\n\n".join(
        f"{c.id}\n{c.start} --> {c.end}\n{c.text}" for c in cues
    ) + "\n"


def remove_sdh(srt_text: str) -> str:
    """Clean SDH elements (sounds, brackets, speaker labels) and renumber cues."""
    cues = parse_srt(srt_text)
    cleaned: List[Cue] = []

    for cue in cues:
        new_lines = []
        for line in cue.text.split("\n"):
            stripped = line
            stripped = SDH_BRACKET_RE.sub("", stripped)
            stripped = SDH_PAREN_RE.sub("", stripped)
            stripped = SDH_ASTERISK_RE.sub("", stripped)
            stripped = SDH_MUSIC_RE.sub("", stripped)
            stripped = SDH_SPEAKER_RE.sub("", stripped)
            stripped = re.sub(r"\s{2,}", " ", stripped).strip()
            if stripped:
                new_lines.append(stripped)

        if new_lines:
            cleaned.append(Cue(
                id=cue.id,
                start=cue.start,
                end=cue.end,
                text="\n".join(new_lines),
            ))

    # Renumber sequentially
    for i, c in enumerate(cleaned):
        c.id = str(i + 1)

    return to_srt(cleaned)


def timecode_to_seconds(tc: str) -> float:
    m = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", tc.strip())
    if not m:
        return 0.0
    h, mn, s, ms = m.groups()
    return int(h) * 3600 + int(mn) * 60 + int(s) + int(ms) / 1000


def seconds_to_timecode(sec: float) -> str:
    sec = max(0, sec)
    h = int(sec // 3600)
    mn = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int((sec % 1) * 1000)
    return f"{h:02d}:{mn:02d}:{s:02d},{ms:03d}"


def cue_duration_seconds(cue: Cue) -> float:
    return max(0.2, timecode_to_seconds(cue.end) - timecode_to_seconds(cue.start))


def max_chars_for_duration(duration_seconds: float, target_cps: int = 17, max_chars: int = 42, max_lines: int = 2) -> int:
    return max(8, min(max_lines * max_chars, round(duration_seconds * target_cps)))


def split_into_two_lines(text: str, max_chars: int = 42) -> str:
    """Split single line into two balanced lines at natural punctuation/conjunctions."""
    if len(text) <= max_chars:
        return text

    break_chars = [", ", " - ", " in ", " da ", " pa ", " ker ", " ko ",
                   " ampak ", " ali ", " zato ", " ko ", ". ", "? ", "! ", " "]

    for bc in break_chars:
        parts = text.split(bc)
        if len(parts) < 2:
            continue
        best_pos = 0
        best_diff = float("inf")
        running_len = 0
        for p in parts[:-1]:
            running_len += len(p) + len(bc)
            other_len = len(text) - running_len
            diff = abs(running_len - other_len)
            if diff < best_diff:
                best_diff = diff
                best_pos = running_len

        if best_pos > 0:
            line1 = text[:best_pos].rstrip()
            line2 = text[best_pos:].lstrip()
            if len(line1) <= max_chars and len(line2) <= max_chars:
                return f"{line1}\n{line2}"

    # Fallback: midpoint split at nearest whitespace
    mid = len(text) // 2
    for offset in range(25):
        for pos in [mid + offset, mid - offset]:
            if 0 < pos < len(text) and text[pos] == " ":
                return f"{text[:pos]}\n{text[pos+1:]}"

    return text


def format_cue_lines(text: str, max_chars: int = 42, max_lines: int = 2) -> str:
    """Ensure cue has at most max_lines, each under max_chars."""
    lines = text.split("\n")
    if len(lines) > max_lines:
        text = " ".join(lines)
        lines = [text]

    formatted = []
    for line in lines:
        if len(line) > max_chars:
            formatted.append(split_into_two_lines(line, max_chars))
        else:
            formatted.append(line)

    return "\n".join(formatted[:max_lines])


def reconcile_srt(source_cues: List[Cue], translated_map: dict) -> List[Cue]:
    """Reconcile translated text map with original cues, strictly preserving IDs and timestamps."""
    result = []
    for src in source_cues:
        text = translated_map.get(str(src.id), "").strip()
        if not text:
            text = src.text
        else:
            text = format_cue_lines(text)
        result.append(Cue(id=src.id, start=src.start, end=src.end, text=text))
    return result


def prepend_notice_cue(srt_text: str, message: str) -> str:
    """Add a reserved 4-second notice cue (id 0) at the very start of the SRT."""
    notice = f"0\n00:00:01,000 --> 00:00:05,000\n{message}\n\n"
    clean_body = re.sub(r"^0\r?\n00:00:0[^\n]*\r?\n[^\n]*\r?\n\r?\n?", "", srt_text or "").lstrip()
    return f"{notice}{clean_body}"
