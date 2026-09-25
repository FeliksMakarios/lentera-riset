"""Pengelompokan makalah per tugas (seperti "Tasks" di Hugging Face).

Tugas dikenali dari kata kunci di judul dan abstrak ([[tasks]] di
config/topics.toml). Satu makalah bisa masuk ke beberapa tugas.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .config import Config, Task


@lru_cache(maxsize=None)
def _pattern(keyword: str) -> re.Pattern:
    parts = re.split(r"[\s\-]+", keyword.strip())
    body = r"[\s\-]+".join(re.escape(p) for p in parts)
    # Singkatan huruf besar ("ASR", "NER", "RAG") dicocokkan persis, supaya
    # kata biasa seperti "rag" atau "lid" tidak ikut cocok.
    flags = 0 if keyword.isupper() else re.IGNORECASE
    return re.compile(rf"(?<!\w){body}s?(?!\w)", flags)


def matches(task: Task, title: str, abstract: str) -> bool:
    text = title if task.title_only else f"{title}\n{abstract}"
    return any(_pattern(kw).search(text) for kw in task.keywords)


def detect(config: Config, paper: dict) -> list[str]:
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    return [t.id for t in config.tasks if matches(t, title, abstract)]
