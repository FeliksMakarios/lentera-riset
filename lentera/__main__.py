"""Titik masuk baris perintah: python -m lentera <perintah>."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import build, pipeline
from .config import load_config


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="lentera", description="Lentera Riset")
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("update", help="ambil makalah, sinyal, dan ringkasan, lalu simpan ke data/")
    up.add_argument("--no-fetch", action="store_true", help="jangan mengambil makalah baru dari arXiv")
    up.add_argument("--no-signals", action="store_true", help="jangan mengumpulkan sinyal popularitas")
    up.add_argument("--no-summaries", action="store_true", help="jangan membuat ringkasan")
    up.add_argument("--no-embeddings", action="store_true", help="jangan membuat vektor makna (embedding)")

    bd = sub.add_parser("build", help="bangun situs statis dari data/papers.json")
    bd.add_argument("--out", default="_site", help="folder keluaran (bawaan: _site)")

    args = parser.parse_args(argv)
    config = load_config()
    if args.command == "update":
        pipeline.update(
            config,
            fetch=not args.no_fetch,
            collect_signals=not args.no_signals,
            summaries=not args.no_summaries,
            vectors=not args.no_embeddings,
        )
    elif args.command == "build":
        build.build_site(config, Path(args.out))


if __name__ == "__main__":
    main()
