"""parenting.py — dérivation de parent par préfixe de chemin (porté de mekistudio, pur).

`longest_prefix_id` : id du candidat dont le `path` est le plus long préfixe (par segments
posix) du chemin cible. `strict` exclut l'égalité (un dossier ne se parente pas lui-même).
Tie-break déterministe : id lexicographiquement le plus petit.
"""
from __future__ import annotations


def _segments(path: str) -> list[str]:
    return [s for s in (path or "").replace("\\", "/").split("/") if s]


def is_prefix(prefix: str, target: str) -> bool:
    ps, ts = _segments(prefix), _segments(target)
    return ps == ts[: len(ps)]


def longest_prefix_id(target_path, candidates, *, strict: bool):
    target_segs = _segments(target_path)
    best_id, best_len = None, -1
    for path, cid in candidates:
        segs = _segments(path)
        if strict and segs == target_segs:
            continue
        if not is_prefix(path, target_path):
            continue
        n = len(segs)
        if n > best_len or (n == best_len and best_id is not None and cid < best_id):
            best_id, best_len = cid, n
    return best_id
