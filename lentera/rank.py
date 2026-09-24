"""Skor gabungan: relevansi topik + keramaian, diturunkan menurut umur makalah."""

from __future__ import annotations

import math
from datetime import datetime, timezone


def parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def age_days(paper: dict, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - parse_date(paper["published"])).total_seconds() / 86400)


def buzz(signals: dict) -> float:
    """Ukuran keramaian dari sinyal-sinyal popularitas, dalam skala logaritmik."""
    hn = signals.get("hacker_news") or {}
    hf = signals.get("hugging_face") or {}
    gh = signals.get("github") or {}
    s2 = signals.get("semantic_scholar") or {}
    return (
        1.0 * math.log1p(hn.get("points", 0))
        + 0.5 * math.log1p(hn.get("comments", 0))
        + 1.5 * math.log1p(hf.get("upvotes", 0))
        + 0.7 * math.log1p(gh.get("stars", 0))
        + 1.0 * math.log1p(s2.get("citations", 0))
        + 1.0 * math.log1p(s2.get("influential", 0))
    )


def score(paper: dict, half_life_days: float, now: datetime | None = None) -> float:
    decay = 0.5 ** (age_days(paper, now) / half_life_days)
    total = (paper.get("relevance", 0.0) + buzz(paper.get("signals", {}))) * decay
    return round(total, 4)
