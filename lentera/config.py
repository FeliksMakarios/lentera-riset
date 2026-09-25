"""Memuat konfigurasi dari config/topics.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "topics.toml"


@dataclass
class Topic:
    id: str
    label_id: str
    label_en: str
    weight: float
    keywords: list[str]
    query: bool = True
    core: bool = True


@dataclass
class Language:
    id: str
    name_id: str
    name_en: str
    group: str
    aliases: list[str]


@dataclass
class Task:
    id: str
    name: str
    group: str
    keywords: list[str]
    # Hanya dicocokkan di judul, untuk kata yang terlalu umum di abstrak
    # (misalnya "dataset" atau "bias").
    title_only: bool = False


@dataclass
class Config:
    site: dict
    arxiv: dict
    ranking: dict
    summaries: dict
    topics: list[Topic] = field(default_factory=list)
    acl: dict = field(default_factory=dict)
    openalex: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    embeddings: dict = field(default_factory=dict)
    search: dict = field(default_factory=dict)
    language_groups: dict = field(default_factory=dict)
    languages: list[Language] = field(default_factory=list)
    task_groups: dict = field(default_factory=dict)
    tasks: list[Task] = field(default_factory=list)

    def topic(self, topic_id: str) -> Topic | None:
        return next((t for t in self.topics if t.id == topic_id), None)

    def source_settings(self, source: str) -> dict:
        """Pengaturan per sumber: "arxiv", "acl", atau "openalex"."""
        return {"acl": self.acl, "openalex": self.openalex}.get(source, self.arxiv)

    def lookback_days(self, source: str) -> float:
        return float(self.source_settings(source).get("lookback_days", 60))


def load_config(path: Path = DEFAULT_CONFIG) -> Config:
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    topics = [
        Topic(
            id=t["id"],
            label_id=t["label_id"],
            label_en=t["label_en"],
            weight=float(t["weight"]),
            keywords=list(t["keywords"]),
            query=bool(t.get("query", True)),
            core=bool(t.get("core", t.get("query", True))),
        )
        for t in raw.get("topics", [])
    ]
    ids = [t.id for t in topics]
    if len(ids) != len(set(ids)):
        raise ValueError("ID topik di config/topics.toml harus unik")
    languages = [
        Language(
            id=l["id"],
            name_id=l["name_id"],
            name_en=l["name_en"],
            group=l.get("group", "other"),
            aliases=list(l.get("aliases") or [l["name_en"]]),
        )
        for l in raw.get("languages", [])
    ]
    tasks = [
        Task(
            id=t["id"],
            name=t["name"],
            group=t.get("group", "other"),
            keywords=list(t["keywords"]),
            title_only=bool(t.get("title_only", False)),
        )
        for t in raw.get("tasks", [])
    ]
    if len({t.id for t in tasks}) != len(tasks):
        raise ValueError("ID tugas di config/topics.toml harus unik")
    lang_ids = [l.id for l in languages]
    if len(lang_ids) != len(set(lang_ids)):
        raise ValueError("ID bahasa di config/topics.toml harus unik")
    return Config(
        site=raw.get("site", {}),
        arxiv=raw.get("arxiv", {}),
        ranking=raw.get("ranking", {}),
        summaries=raw.get("summaries", {}),
        topics=topics,
        acl=raw.get("acl", {}),
        openalex=raw.get("openalex", {}),
        signals=raw.get("signals", {}),
        embeddings=raw.get("embeddings", {}),
        search=raw.get("search", {}),
        language_groups=raw.get("language_groups", {}),
        languages=languages,
        task_groups=raw.get("task_groups", {}),
        tasks=tasks,
    )
