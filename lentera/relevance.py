"""Penilaian relevansi berbasis kata kunci per topik."""

from __future__ import annotations

import re
from functools import lru_cache

from .config import Config, Topic

# Batas kontribusi satu topik, dalam kelipatan bobotnya, supaya satu topik
# yang disebut berulang kali tidak mendominasi skor.
TOPIC_CAP_MULTIPLIER = 3
TITLE_BONUS = 1.0


@lru_cache(maxsize=None)
def _pattern(keyword: str) -> re.Pattern:
    # Spasi dan tanda hubung dianggap setara ("low-resource" = "low resource").
    parts = re.split(r"[\s\-]+", keyword.strip())
    body = r"[\s\-]+".join(re.escape(p) for p in parts)
    return re.compile(rf"(?<![\w-]){body}(?![\w-])", re.IGNORECASE)


def topic_matches(topic: Topic, title: str, abstract: str) -> tuple[list[str], float]:
    """Kembalikan kata kunci yang cocok dan skor topik tersebut."""
    matched: list[str] = []
    score = 0.0
    for kw in topic.keywords:
        pat = _pattern(kw)
        in_title = bool(pat.search(title))
        in_abstract = bool(pat.search(abstract))
        if in_title or in_abstract:
            matched.append(kw)
            score += topic.weight * (1 + (TITLE_BONUS if in_title else 0))
    return matched, min(score, topic.weight * TOPIC_CAP_MULTIPLIER)


def score_paper(config: Config, paper: dict) -> dict:
    """Hitung relevansi dan kembalikan {'relevance', 'topics', 'matched_keywords'}."""
    total = 0.0
    topics: list[str] = []
    matched_all: dict[str, list[str]] = {}
    for topic in config.topics:
        matched, score = topic_matches(topic, paper.get("title", ""), paper.get("abstract", ""))
        if matched:
            topics.append(topic.id)
            matched_all[topic.id] = matched
            total += score
    return {"relevance": round(total, 3), "topics": topics, "matched_keywords": matched_all}
