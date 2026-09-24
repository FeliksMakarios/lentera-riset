from lentera.config import load_config

CONFIG = load_config()


def _both(en: str, idn: str) -> dict:
    return {"en": en, "id": idn}


# Contoh keluaran Gemini (format ringkasan versi 2).
SUMMARY = {
    "tldr": _both(
        "Studies low-resource MT for Javanese and Sundanese. NusaX-based models improve BLEU.",
        "Mengkaji terjemahan mesin *low-resource* untuk bahasa Jawa dan Sunda. Model berbasis NusaX meningkatkan BLEU.",
    ),
    "sections": {
        "background": _both("Background paragraph.\n\nSecond paragraph.", "Paragraf latar belakang dengan *benchmark* NusaX.\n\nParagraf kedua."),
        "related_work": _both("Related work.", "Penelitian terkait."),
        "contributions": _both("Contributions.", "Kontribusi."),
        "method": _both("Method with *fine-tuning*.", "Metode dengan *fine-tuning*."),
        "results": _both("Results.", "Hasil."),
        "future_work": _both("Future work.", "Penelitian selanjutnya."),
    },
    "glossary": [{"term": "*benchmark*", "explanation_id": "Tolok ukur untuk membandingkan model."}],
    "languages_studied": ["Javanese", "Sundanese"],
}
