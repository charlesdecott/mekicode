#!/usr/bin/env python3
"""render.py — sert le repo en HTTP local et capture chaque frame du trailer via Playwright.

Déterministe : pour chaque frame, on appelle window.seekFrame(t) qui (1) positionne toute la
motion comme fonction pure de t et (2) recale les @keyframes CSS d'ambiance à currentTime=t.

Usage :
    python render.py              # rend toutes les frames -> frames/f%05d.png
    python render.py 30           # limite aux 30 premières frames (smoke)
    python render.py --at 16000   # rend UNE frame a t=16000 ms -> frames/at.png (inspection)
"""
from __future__ import annotations

import functools
import http.server
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent          # racine du repo
TRAILER = Path(__file__).resolve().parent
FRAMES = TRAILER / "frames"
W, H = 1920, 1080


def _serve() -> tuple[socketserver.TCPServer, int]:
    """Sert ROOT sur 127.0.0.1:<port libre> (silencieux), en thread démon."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    httpd.RequestHandlerClass.log_message = lambda *a, **k: None
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def _new_page(p, port):
    b = p.chromium.launch(args=["--force-color-profile=srgb", "--hide-scrollbars",
                                "--disable-lcd-text"])
    pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    pg.goto(f"http://127.0.0.1:{port}/trailer/trailer.html", wait_until="networkidle")
    pg.wait_for_function("typeof window.seekFrame === 'function'")
    pg.wait_for_timeout(250)   # laisse les polices/anims s'initialiser
    return b, pg


def render_one(at_spec: str) -> int:
    """Rend une frame par timestamp (ms) listé, séparés par des virgules.
    `--at 1500` -> frames/at.png ; `--at 1500,8000` -> frames/at_1500.png, at_8000.png."""
    stamps = [int(x) for x in str(at_spec).split(",") if x.strip()]
    FRAMES.mkdir(parents=True, exist_ok=True)
    httpd, port = _serve()
    try:
        with sync_playwright() as p:
            b, pg = _new_page(p, port)
            for at_ms in stamps:
                pg.evaluate("(t)=>window.seekFrame(t)", at_ms)
                out = FRAMES / ("at.png" if len(stamps) == 1 else f"at_{at_ms}.png")
                pg.screenshot(path=str(out), animations="disabled")
                print(f"[render] frame @ {at_ms}ms -> {out}")
            b.close()
    finally:
        httpd.shutdown()
    return 0


def render(fps: int | None = None, dur_ms: int | None = None, limit: int | None = None) -> int:
    """Rend toutes les frames (ou les `limit` premières) -> frames/f%05d.png."""
    FRAMES.mkdir(parents=True, exist_ok=True)
    for old in FRAMES.glob("f*.png"):
        old.unlink()
    httpd, port = _serve()
    n_total = None
    try:
        with sync_playwright() as p:
            b, pg = _new_page(p, port)
            tl = pg.evaluate("window.TL")
            fps = fps or tl["FPS"]
            dur_ms = dur_ms or tl["DUR"]
            n = int(dur_ms * fps / 1000)
            if limit:
                n = min(n, limit)
            n_total = n
            for i in range(n):
                t = round(i * 1000 / fps)
                pg.evaluate("(t)=>window.seekFrame(t)", t)
                pg.screenshot(path=str(FRAMES / f"f{i:05d}.png"), animations="disabled")
                if i % 60 == 0:
                    print(f"  … frame {i}/{n}")
            b.close()
    finally:
        httpd.shutdown()
    print(f"[render] {n_total} frames -> {FRAMES}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--at":
        raise SystemExit(render_one(args[1]))
    lim = int(args[0]) if args else None
    raise SystemExit(render(limit=lim))
