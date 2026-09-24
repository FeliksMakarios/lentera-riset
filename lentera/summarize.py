"""Ringkasan dwibahasa (Inggris dan Indonesia) memakai Gemini API versi gratis."""

from __future__ import annotations

import base64
import json
import os
import re
import time

from . import http

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

SUMMARY_VERSION = 2

# Urutan dan judul bagian ringkasan. Kunci dipakai di data, judul dipakai di situs.
SECTIONS = [
    ("background", "Latar belakang masalah", "Background"),
    ("related_work", "Penelitian terkait", "Related work"),
    ("contributions", "Kontribusi dan kebaruan", "Contributions and novelty"),
    ("method", "Metode", "Method"),
    ("results", "Hasil dan pembahasan", "Results and discussion"),
    ("future_work", "Penelitian selanjutnya", "Future work"),
]

TERMINOLOGY_RULES = """Language rules:
- "en": natural academic English. Do not use asterisks or any markup in "en".
- "id": natural, formal Indonesian (bahasa Indonesia baku), carrying exactly the same
  content as "en". Terminology rules for "id":
  - Keep established English technical terms in English and wrap them in single
    asterisks, e.g. *fine-tuning*, *benchmark*, *low-resource*, *tokenizer*,
    *zero-shot*, *large language model*. Do NOT force literal translations that
    Indonesian NLP researchers would not recognise.
  - Use Indonesian only where the equivalent is well established in Indonesian
    academic writing (e.g. "terjemahan mesin", "korpus", "anotasi", "model bahasa").
    Indonesian words, including loanwords already absorbed into Indonesian such as
    "anotasi", "dialek", "evaluasi", "data", are NEVER wrapped in asterisks. Only
    English terms are wrapped, and only the term itself, never Indonesian affixes
    (write "data beranotasi", not "ber-*anotasi*").
  - Never translate names of models, datasets, benchmarks, metrics or languages
    (write "bahasa Jawa" for the language, but keep "NusaX", "BLEU", "IndoBERT")."""

PROMPT = """You are an expert NLP researcher writing a structured paper summary for
Indonesian researchers and students. {source_note}
Never invent numbers, datasets, languages, baselines or results that are not in the source.

{rules}

Write the following, each with an "en" and an "id" version:

1. "tldr": EXACTLY two sentences summarising the ABSTRACT only, in the style of the
   Semantic Scholar TL;DR: the first sentence says what the paper does, the second
   says the main finding or takeaway. At most 60 words in total.

2. "sections": six sections. Each is one or two well-organised paragraphs (separated
   by a blank line), clear, logically ordered and easy to follow, yet technical:
   - "background": the problem, why it matters, and the gap the paper addresses.
   - "related_work": the prior approaches or studies the paper builds on or compares
     with, and their limitations as the authors describe them.
   - "contributions": what is new: the specific contributions and their novelty.
   - "method": how the problem is solved: data, models, training or annotation
     procedure, and evaluation setup, with the key design choices.
   - "results": the main quantitative and qualitative findings, including the most
     important numbers and comparisons, and how the authors interpret them.
   - "future_work": limitations and future directions stated by the authors.
   If the source does not cover a section, write one sentence saying so
   (for example "The paper does not discuss related work in detail.") instead of
   guessing.

3. "glossary": up to eight technical terms used in the Indonesian text that a
   master's student might not know. For each give "term" (exactly as written in the
   text, without asterisks) and "explanation_id" (one plain Indonesian sentence,
   where English terms follow the same asterisk rule as "id").

4. "languages_studied": names of natural languages the paper explicitly studies,
   in English (e.g. "Javanese", "Tagalog"). Empty list if none are named.

Title: {title}

Abstract: {abstract}

Author comment: {comment}
"""

SOURCE_NOTE_FULL = (
    "The full paper is attached as a PDF. Base the six sections on the full text, "
    "and the TL;DR on the abstract."
)
SOURCE_NOTE_ABSTRACT = (
    "Only the title, abstract and author comment are available, so base everything "
    "on them."
)

_BILINGUAL = {
    "type": "OBJECT",
    "properties": {"en": {"type": "STRING"}, "id": {"type": "STRING"}},
    "required": ["en", "id"],
}

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "tldr": _BILINGUAL,
        "sections": {
            "type": "OBJECT",
            "properties": {key: _BILINGUAL for key, _, _ in SECTIONS},
            "required": [key for key, _, _ in SECTIONS],
        },
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
    "required": ["tldr", "sections", "glossary", "languages_studied"],
}


class QuotaExceeded(Exception):
    """Kuota harian semua model habis; sisa makalah diringkas pada jalankan berikutnya."""


class ModelUnavailable(Exception):
    """Model tidak ada (404) atau sudah tidak dilayani."""


class ModelBusy(Exception):
    """Model sedang sibuk (503) walaupun sudah dicoba ulang."""


class RateLimited(Exception):
    """Kena batas permintaan (429). `daily` berarti kuota harian model ini habis."""

    def __init__(self, message: str, daily: bool):
        super().__init__(message)
        self.daily = daily


def _strip_marks(text: str) -> str:
    return re.sub(r"\*([^*\n]+?)\*", r"\1", str(text))


def _bilingual(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"'{name}' tidak ada")
    en = _strip_marks(str(value.get("en", "")).strip())
    idn = str(value.get("id", "")).strip()
    if not en or not idn:
        raise ValueError(f"'{name}' kosong")
    return {"en": en, "id": idn}


def validate(summary: dict) -> dict:
    """Pastikan struktur keluaran model lengkap; lempar ValueError jika tidak.

    Versi Inggris tidak memerlukan penanda istilah, jadi tanda bintangnya dibuang.
    """
    sections = summary.get("sections")
    if not isinstance(sections, dict):
        raise ValueError("'sections' tidak ada")
    out = {
        "version": SUMMARY_VERSION,
        "tldr": _bilingual(summary.get("tldr"), "tldr"),
        "sections": {key: _bilingual(sections.get(key), key) for key, _, _ in SECTIONS},
    }
    out["glossary"] = [
        {"term": str(g["term"]).strip().strip("*"), "explanation_id": str(g["explanation_id"]).strip()}
        for g in summary.get("glossary") or []
        if isinstance(g, dict) and g.get("term") and g.get("explanation_id")
    ]
    out["languages_studied"] = [str(x).strip() for x in summary.get("languages_studied") or [] if str(x).strip()]
    return out


def build_request(paper: dict, pdf: bytes | None) -> dict:
    prompt = PROMPT.format(
        source_note=SOURCE_NOTE_FULL if pdf else SOURCE_NOTE_ABSTRACT,
        rules=TERMINOLOGY_RULES,
        title=paper["title"],
        abstract=paper.get("abstract") or "-",
        comment=paper.get("comment") or "-",
    )
    parts: list[dict] = []
    if pdf:
        parts.append({"inlineData": {"mimeType": "application/pdf", "data": base64.b64encode(pdf).decode("ascii")}})
    parts.append({"text": prompt})
    return {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }


class BadRequest(Exception):
    """Permintaan ditolak (400), misalnya PDF tidak bisa dibaca model."""


def call_gemini(model: str, api_key: str, paper: dict, pdf: bytes | None = None) -> dict:
    payload = build_request(paper, pdf)
    try:
        # Status 5xx (misalnya 503 "high demand") dicoba ulang dengan jeda 10, 20, 40 detik.
        data = http.post_json(
            API_URL.format(model=model),
            payload,
            headers={"x-goog-api-key": api_key},
            timeout=300,
            retries=4,
            backoff=10,
        )
    except http.HttpError as exc:
        if exc.status == 429:
            raise RateLimited(str(exc), daily="PerDay" in exc.body) from exc
        if exc.status == 404:
            raise ModelUnavailable(model) from exc
        if exc.status == 400:
            raise BadRequest(str(exc)) from exc
        if exc.status >= 500:
            raise ModelBusy(model) from exc
        raise
    try:
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError) as exc:
        raise ValueError(f"respons Gemini tidak berisi teks: {json.dumps(data)[:300]}") from exc
    return validate(json.loads(text))


def list_flash_models(api_key: str) -> list[str]:
    """Cari model Flash yang tersedia untuk kunci ini, dipakai jika semua model di konfigurasi hilang."""
    data = http.get_json(f"{MODELS_URL}?pageSize=200", headers={"x-goog-api-key": api_key})
    names = []
    for m in data.get("models", []):
        name = m.get("name", "").removeprefix("models/")
        if (
            "flash" in name
            and "generateContent" in m.get("supportedGenerationMethods", [])
            and not any(x in name for x in ("image", "tts", "audio", "live", "embedding", "preview", "exp"))
        ):
            names.append(name)
    # Utamakan alias "-latest", lalu bukan "lite", lalu versi terbaru.
    names.sort(reverse=True)
    return sorted(names, key=lambda n: (not n.endswith("-latest"), "lite" in n))


class Summarizer:
    def __init__(self, models: list[str], api_key: str | None = None, log=print, sleep=time.sleep):
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        self.models = list(models)
        self.log = log
        self.sleep = sleep
        self._discovered = False

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _discover(self) -> int:
        """Tambahkan model Flash lain yang tersedia ke akhir daftar (sekali per jalankan).

        Kembalikan jumlah model baru yang ditambahkan.
        """
        self._discovered = True
        try:
            found = list_flash_models(self.api_key)
        except Exception as exc:
            self.log(f"  [Gemini] gagal mencari daftar model: {exc}")
            return 0
        extra = [m for m in found if m not in self.models][:3]
        self.models.extend(extra)
        self.log(f"  [Gemini] model cadangan ditambahkan: {', '.join(extra) or '-'}")
        return len(extra)

    def summarize(self, paper: dict, pdf: bytes | None = None) -> tuple[dict, str]:
        """Kembalikan (ringkasan, nama model). Kolom `source` di ringkasan berisi
        "full_text" jika PDF ikut dibaca, atau "abstract" jika hanya abstrak.

        - PDF ditolak model (400): ulangi dengan abstrak saja.

        - Model 404 dibuang.
        - Model sibuk (503) atau kena batas per menit: coba model berikutnya untuk makalah ini.
        - Jika semua model habis atau sibuk, model Flash lain dicari otomatis (sekali per jalankan).
          Batas per menit juga diberi jeda 60 detik sebelum makalah berikutnya.
        - Kuota harian habis: model itu dibuang untuk sisa jalankan ini.
        Melempar QuotaExceeded jika tidak ada model yang bisa dipakai lagi.
        """
        busy = 0
        i = 0
        while True:
            if i >= len(self.models) and not self._discovered and self._discover():
                continue
            if not self.models:
                raise QuotaExceeded("tidak ada model Gemini yang bisa dipakai")
            if i >= len(self.models):
                raise ModelBusy(f"semua model sibuk ({busy} percobaan)")
            model = self.models[i]
            try:
                result = call_gemini(model, self.api_key, paper, pdf)
                result["source"] = "full_text" if pdf else "abstract"
                return result, model
            except BadRequest as exc:
                if not pdf:
                    raise
                self.log(f"  [Gemini] PDF {paper.get('id', '')} ditolak ({str(exc)[:120]}), memakai abstrak")
                pdf = None
            except ModelUnavailable:
                self.log(f"  [Gemini] model {model} tidak tersedia")
                self.models.pop(i)
            except RateLimited as exc:
                if exc.daily:
                    self.log(f"  [Gemini] kuota harian {model} habis")
                    self.models.pop(i)
                else:
                    self.log(f"  [Gemini] batas per menit {model}, jeda 60 detik")
                    self.sleep(60)
                    busy += 1
                    i += 1
            except ModelBusy:
                self.log(f"  [Gemini] model {model} sedang sibuk")
                busy += 1
                i += 1
