from lentera.config import load_config

CONFIG = load_config()

SUMMARY = {
    "en": {
        "tldr": "Studies low-resource MT for Javanese and Sundanese.",
        "summary": "Problem paragraph.\n\nFindings paragraph.",
        "key_points": ["Uses NusaX", "Two regional languages"],
    },
    "id": {
        "tldr": "Mengkaji terjemahan mesin *low-resource* untuk bahasa Jawa dan Sunda.",
        "summary": "Paragraf masalah dengan *benchmark* NusaX.\n\nParagraf temuan.",
        "key_points": ["Memakai NusaX", "Dua bahasa daerah"],
    },
    "glossary": [{"term": "*benchmark*", "explanation_id": "Tolok ukur untuk membandingkan model."}],
    "languages_studied": ["Javanese", "Sundanese"],
}
