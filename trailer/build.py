#!/usr/bin/env python3
"""build.py — pipeline complet du trailer, 100% automatique.

    python trailer/build.py

Étapes : (polices best-effort) → render des frames (Playwright, déterministe) →
encodage MP4 (ffmpeg, H.264, muet) → poster.png + preview.gif.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import render as render_mod  # noqa: E402

FRAMES = HERE / "frames"
OUT = HERE / "out"
MP4 = OUT / "mekicode-trailer.mp4"
POSTER = OUT / "poster.png"
GIF = OUT / "preview.gif"
FPS = 30


def _run(cmd: list[str]) -> None:
    print("[ffmpeg]", " ".join(cmd[1:7]), "…")
    subprocess.run(cmd, check=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    # 1) polices (best-effort : si offline, le <link> reseau prend le relais au render)
    subprocess.run([sys.executable, str(HERE / "fetch_fonts.py")], check=False)
    # 2) frames
    render_mod.render()
    pattern = str(FRAMES / "f%05d.png")
    # 3) MP4 muet (H.264, yuv420p, faststart)
    _run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", pattern,
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "slow",
          "-movflags", "+faststart", "-an", str(MP4)])
    # 4) poster (miniature YouTube) : la frame logo (boot, t≈1,5 s) — brandée & lisible en petit
    poster_frame = FRAMES / f"f{45:05d}.png"
    if poster_frame.exists():
        _run(["ffmpeg", "-y", "-i", str(poster_frame), str(POSTER)])
    # 5) preview.gif : slice gameplay ~3,5 s, 15 fps, 960px, palette propre
    _run(["ffmpeg", "-y", "-ss", "15", "-t", "3.5", "-i", str(MP4),
          "-vf", "fps=15,scale=960:-1:flags=lanczos,split[s0][s1];"
                 "[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer", str(GIF)])
    print(f"[build] OK\n  {MP4}\n  {POSTER}\n  {GIF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
