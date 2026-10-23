"""Which language subtitle text is in, worked out from its letters by fixed rules, and which
language an audio track is tagged with.

Exported text must be in the language spoken in the video (see docs/DECISIONS.md). Subtitles come
in that language, in a translation, or in both at once: bilingual files put the two languages on two
lines of one entry, or in two styles. So the language is decided line by line:

- Two or more kana mean Japanese, two or more Hangul mean Korean. One alone is not enough, because
  Chinese subtitles sometimes borrow の as decoration.
- Any other line (Chinese characters only, Latin letters, digits) follows the language most common
  at its place in the file: its style, and its line number within the entry. Japanese lines with
  no kana, such as ６連勝 or 押忍！, are 2% to 3% of our four Japanese sources, and they sit among
  Japanese lines.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence

from avoc.language import Words

LANGUAGES: dict[str, Words] = {
    "ja": Words("日语", "Japanese"),
    "zh": Words("中文", "Chinese"),
    "en": Words("英语", "English"),
    "ko": Words("韩语", "Korean"),
}
"""The languages the training formats take, as codes and as names for the person."""

ASSUMED = "ja"
"""The spoken language when nothing says otherwise: this is a tool for anime."""

KANA = re.compile(r"[ぁ-ゖァ-ヺ]")
HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")
HAN = re.compile(r"[一-鿿㐀-䶿々]")
LATIN = re.compile(r"[A-Za-zÀ-ɏ]")

MIN_SHARE = 0.3
"""A place in the file is Japanese (or Korean) when at least this share of its lines are clearly
Japanese (or Korean). In our Japanese subtitles it was 97%, in our Chinese ones 0%."""

IN_FILE = 0.3
"""A subtitle file counts as having a language when at least this share of its lines are in it.
A bilingual file has about half in each."""

TRACK_TAGS = {
    "ja": "ja", "jpn": "ja", "jp": "ja",
    "zh": "zh", "chi": "zh", "zho": "zh", "cmn": "zh", "chs": "zh", "cht": "zh",
    "en": "en", "eng": "en",
    "ko": "ko", "kor": "ko",
}  # fmt: skip
"""Language tags of audio tracks in video files (mostly ISO 639-2, as Matroska writes them)."""


def name_of(code: str) -> str:
    words = LANGUAGES.get(code)
    return str(words) if words else code


def from_tag(tag: str | None) -> str | None:
    """The language of an audio track's tag. None for no tag, `und`, or a language not listed."""
    return TRACK_TAGS.get((tag or "").strip().lower().split("-")[0])


def clear_language(text: str) -> str | None:
    """Japanese or Korean when the letters leave no doubt, otherwise None."""
    if len(KANA.findall(text)) >= 2:
        return "ja"
    if len(HANGUL.findall(text)) >= 2:
        return "ko"
    return None


def place_language(texts: Sequence[str]) -> str | None:
    """The language of the lines at one place in a file. None if none of them has letters."""
    if not texts:
        return None
    clear = Counter(clear_language(t) for t in texts)
    for code in ("ja", "ko"):
        if clear[code] >= MIN_SHARE * len(texts):
            return code
    han = sum(bool(HAN.search(t)) for t in texts)
    latin = sum(bool(LATIN.search(t)) and not HAN.search(t) for t in texts)
    if han == latin == 0:
        return None
    return "zh" if han >= latin else "en"


Place = tuple[str, int]
"""Where a line sits in a file: its style, and its line number within the entry."""


def line_languages(entries: Iterable[tuple[str, list[str]]]) -> list[list[str | None]]:
    """The language of each line, for entries given as (style, lines)."""
    entries = list(entries)
    by_place: dict[Place, list[str]] = {}
    for style, lines in entries:
        for k, line in enumerate(lines):
            by_place.setdefault((style, k), []).append(line)
    places = {place: place_language(texts) for place, texts in by_place.items()}
    return [
        [clear_language(line) or places[(style, k)] for k, line in enumerate(lines)]
        for style, lines in entries
    ]


def file_languages(found: Iterable[str | None]) -> dict[str, float]:
    """The languages that make up at least `IN_FILE` of a file's lines, with their shares, most
    first."""
    counts = Counter(code for code in found if code)
    total = sum(counts.values())
    if not total:
        return {}
    return {code: round(n / total, 3) for code, n in counts.most_common() if n >= IN_FILE * total}


def languages_note(languages: dict[str, float]) -> str:
    """For the person: "Chinese", or "Chinese and Japanese" for a bilingual file."""
    if not languages:
        return str(Words("认不出语言", "language not recognized"))
    return str(Words("和", " and ")).join(name_of(code) for code in languages)
