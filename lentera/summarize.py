"""Ringkasan dwibahasa (Inggris dan Indonesia) memakai Gemini API versi gratis."""

from __future__ import annotations

import json
import os

from . import http

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """You are an expert NLP researcher writing for Indonesian researchers and students.
Summarise the arXiv paper below using ONLY the information in its title, abstract and
author comment. Never invent numbers, datasets, languages or results that are not stated.

Produce two versions with the same content:

1. "en": natural academic English.
2. "id": natural, formal Indonesian (bahasa Indonesia baku). Terminology rules for "id":
   - Keep established English technical terms in English and wrap them in single
     asterisks, e.g. *fine-tuning*, *benchmark*, *low-resource*, *tokenizer*,
     *zero-shot*, *large language model*. Do NOT force literal translations that
     Indonesian NLP researchers would not recognise.
   - Use Indonesian only where the equivalent is well established in Indonesian
     academic writing (e.g. "terjemahan mesin", "korpus", "anotasi", "model bahasa").
   - Never translate names of models, datasets, benchmarks, metrics or languages
     (write "bahasa Jawa" for the language, but keep "NusaX", "BLEU", "IndoBERT").

For each version write:
- "tldr": one sentence, at most 35 words.
- "summary": two short paragraphs separated by a blank line (problem and approach;
  findings and significance). Mention the languages studied if stated.
- "key_points": three to five short bullet points.

Also produce:
- "glossary": up to six technical terms used in the Indonesian version that a
  master's student might not know. For each give "term" (exactly as written in the
  text, without asterisks) and "explanation_id" (one plain Indonesian sentence).
- "languages_studied": names of natural languages the paper explicitly studies,
  in English (e.g. "Javanese", "Tagalog"). Empty list if none are named.

Title: {title}

Abstract: {abstract}

Author comment: {comment}
"""

_SECTION = {
    "type": "OBJECT",
    "properties": {
        "tldr": {"type": "STRING"},
        "summary": {"type": "STRING"},
        "key_points": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["tldr", "summary", "key_points"],
}

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "en": _SECTION,
        "id": _SECTION,
        "glossary": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "term": {"type": "STRING"},
                    "explanation_id": {"type": "STRING"},
                },
                "required": ["term", "explanation_id"],
            },
        },
        "languages_studied": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["en", "id", "glossary", "languages_studied"],
}


class QuotaExceeded(Exception):
    """Kuota gratis habis untuk saat ini; sisa makalah diringkas pada jalankan berikutnya."""


class ModelUnavailable(Exception):
    pass


def validate(summary: dict) -> dict:
    """Pastikan struktur keluaran model lengkap; lempar ValueError jika tidak."""
    for lang in ("en", "id"):
        section = summary.get(lang)
        if not isinstance(section, dict):
            raise ValueError(f"bagian '{lang}' tidak ada")
        if not str(section.get("tldr", "")).strip() or not str(section.get("summary", "")).strip():
            raise ValueError(f"tldr atau summary '{lang}' kosong")
        points = section.get("key_points")
        if not isinstance(points, list) or not points:
            raise ValueError(f"key_points '{lang}' kosong")
        section["key_points"] = [str(p).strip() for p in points if str(p).strip()]
    glossary = summary.get("glossary") or []
    summary["glossary"] = [
        {"term": str(g["term"]).strip().strip("*"), "explanation_id": str(g["explanation_id"]).strip()}
        for g in glossary
        if isinstance(g, dict) and g.get("term") and g.get("explanation_id")
    ]
    summary["languages_studied"] = [str(x).strip() for x in summary.get("languages_studied") or [] if str(x).strip()]
    return summary


def call_gemini(model: str, api_key: str, paper: dict) -> dict:
    prompt = PROMPT.format(
        title=paper["title"], abstract=paper["abstract"], comment=paper.get("comment") or "-"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }
    try:
        data = http.post_json(
            API_URL.format(model=model),
            payload,
            headers={"x-goog-api-key": api_key},
            timeout=120,
        )
    except http.HttpError as exc:
        if exc.status == 429:
            raise QuotaExceeded(str(exc)) from exc
        if exc.status == 404:
            raise ModelUnavailable(model) from exc
        raise
    try:
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError) as exc:
        raise ValueError(f"respons Gemini tidak berisi teks: {json.dumps(data)[:300]}") from exc
    return validate(json.loads(text))


class Summarizer:
    def __init__(self, models: list[str], api_key: str | None = None):
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        self.models = list(models)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def summarize(self, paper: dict) -> tuple[dict, str]:
        """Kembalikan (ringkasan, nama model). Model yang tidak tersedia dibuang dari daftar."""
        while self.models:
            model = self.models[0]
            try:
                return call_gemini(model, self.api_key, paper), model
            except ModelUnavailable:
                self.models.pop(0)
        raise ModelUnavailable("tidak ada model Gemini yang tersedia")
