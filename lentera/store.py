"""Penyimpanan data makalah dalam satu berkas JSON di dalam repositori."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT

DEFAULT_STORE = ROOT / "data" / "papers.json"


def load(path: Path = DEFAULT_STORE) -> dict:
    if not path.exists():
        return {"updated_at": None, "papers": {}}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("papers", {})
    return data


def save(data: dict, path: Path = DEFAULT_STORE) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)
