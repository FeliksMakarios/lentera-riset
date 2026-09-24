"""Penilaian relevansi berbasis kata kunci per topik."""

from __future__ import annotations

import re
from functools import lru_cache

from .config import Config, Topic

# Batas kontribusi satu topik, dalam kelipatan bobotnya, supaya satu topik
# yang disebut berulang kali tidak mendominasi skor.
TOPIC_CAP_MULTIPLIER = 3
TITLE_BONUS = 1.0


def _normalize(keyword: str) -> str:
    return " ".join(re.split(r"[\s\-]+", keyword.strip().lower()))


@lru_cache(maxsize=None)
def _pattern(keyword: str) -> re.Pattern:
    # Spasi dan tanda hubung dianggap setara ("low-resource" = "low resource"),
    # dan bentuk jamak dengan akhiran -s ikut cocok ("language" = "languages").
    parts = re.split(r"[\s\-]+", keyword.strip())
    body = r"[\s\-]+".join(re.escape(p) for p in parts)
    return re.compile(rf"(?<![\w-]){body}s?(?![\w-])", re.IGNORECASE)


def topic_matches(topic: Topic, title: str, abstract: str) -> tuple[list[str], float]:
    """Kembalikan kata kunci yang cocok dan skor topik tersebut.

    Kata kunci yang setara (misalnya "low-resource" dan "low resource") hanya dihitung sekali.
    """
    matched: list[str] = []
    seen: set[str] = set()
    score = 0.0
    for kw in topic.keywords:
        norm = _normalize(kw)
        if norm in seen:
            continue
        seen.add(norm)
        pat = _pattern(kw)
        in_title = bool(pat.search(title))
        in_abstract = bool(pat.search(abstract))
        if in_title or in_abstract:
            matched.append(kw)
            score += topic.weight * (1 + (TITLE_BONUS if in_title else 0))
    return matched, min(score, topic.weight * TOPIC_CAP_MULTIPLIER)


def score_paper(config: Config, paper: dict) -> dict:
    """Hitung relevansi dan kembalikan {'relevance', 'topics', 'matched_keywords'}.

    Topik pendukung (`core = false`) hanya menambah skor jika makalah juga cocok
    dengan minimal satu topik inti. Tanpa topik inti, relevansinya 0, sehingga
    makalah yang sekadar "multilingual" tidak ikut masuk.
    """
    total = 0.0
    has_core = False
    topics: list[str] = []
    matched_all: dict[str, list[str]] = {}
    for topic in config.topics:
        matched, score = topic_matches(topic, paper.get("title", ""), paper.get("abstract", ""))
        if matched:
            topics.append(topic.id)
            matched_all[topic.id] = matched
            total += score
            has_core = has_core or topic.core
    if not has_core:
        total = 0.0
    return {"relevance": round(total, 3), "topics": topics, "matched_keywords": matched_all}
