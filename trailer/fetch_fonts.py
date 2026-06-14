#!/usr/bin/env python3
"""Télécharge Share Tech Mono + Chakra Petch (.woff2) dans assets/fonts/ et génère
fonts.css (@font-face locaux). Best-effort : si le réseau échoue, trailer.html garde le
<link> Google Fonts en repli. Idempotent (réécrit fonts.css à chaque passage)."""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

DST = Path(__file__).resolve().parent / "assets" / "fonts"
CSS_OUT = DST / "fonts.css"
CSS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Chakra+Petch:wght@400;600;700&family=Share+Tech+Mono&display=swap"
)
# UA navigateur → Google renvoie des @font-face woff2 modernes
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def _family_of(block: str) -> str | None:
    m = re.search(r"font-family:\s*'([^']+)'", block)
    return m.group(1) if m else None


def _weight_of(block: str) -> str:
    m = re.search(r"font-weight:\s*(\d+)", block)
    return m.group(1) if m else "400"


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(CSS_URL, headers=UA)
        css = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
    except Exception as e:  # offline / blocage réseau
        print(f"[fonts] CSS Google inaccessible ({e}) — repli sur le <link> reseau.")
        return 0

    # un bloc @font-face par variante ; on ne garde que le 1er src woff2 de chaque bloc
    faces_css: list[str] = []
    n = 0
    for block in re.findall(r"@font-face\s*{[^}]+}", css):
        fam = _family_of(block)
        url_m = re.search(r"url\((https://[^)]+\.woff2)\)", block)
        if not (fam and url_m):
            continue
        weight = _weight_of(block)
        fname = f"{fam.replace(' ', '')}_{weight}_{n:02d}.woff2"
        try:
            data = urllib.request.urlopen(
                urllib.request.Request(url_m.group(1), headers=UA), timeout=20).read()
            (DST / fname).write_bytes(data)
        except Exception as e:
            print(f"[fonts] skip {fname}: {e}")
            continue
        faces_css.append(
            "@font-face{font-family:'%s';font-style:normal;font-weight:%s;"
            "font-display:swap;src:url('%s') format('woff2')}" % (fam, weight, fname))
        n += 1

    if faces_css:
        CSS_OUT.write_text("\n".join(faces_css) + "\n", encoding="utf-8")
        print(f"[fonts] {n} variante(s) woff2 -> {DST} ; fonts.css genere.")
    else:
        print("[fonts] aucun woff2 recupere — repli sur le <link> reseau.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
