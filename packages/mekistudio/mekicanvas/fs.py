"""fs.py — helpers fichiers du canvas, SANDBOXÉS à une racine (workspace de session).

Pur, sans dépendance NiceGUI. Toute opération résout le chemin sous `root` et **rejette** ce qui
s'en échappe (`..`, absolu hors racine). Lecture texte plafonnée + refus du binaire ; écriture atomique.
"""
from __future__ import annotations

import uuid
from pathlib import Path

MAX_BYTES = 1_000_000  # 1 Mo : au-delà on refuse la lecture (gros fichiers / dumps)
DEFAULT_EXCLUDES = ("__pycache__", ".git", ".venv", "node_modules", ".mypy_cache", ".pytest_cache")


def safe_path(root, rel: str) -> Path:
    """Résout `rel` sous `root` ; lève ValueError s'il s'en échappe (absolu hors racine, `..`)."""
    base = Path(root).resolve()
    target = (base / (rel or "")).resolve()
    if target != base and base not in target.parents:
        raise ValueError(f"chemin hors de la racine : {rel}")
    return target


def list_dir(root, rel: str = "", excludes=DEFAULT_EXCLUDES) -> list[dict]:
    """Entrées d'un dossier : dossiers d'abord (alpha), puis fichiers (alpha). `path` = relatif posix."""
    base = Path(root).resolve()
    target = safe_path(base, rel)
    if not target.is_dir():
        raise ValueError(f"pas un dossier : {rel}")
    ex = set(excludes or ())
    rel_norm = (rel or "").replace("\\", "/").strip("/")
    out = []
    for p in target.iterdir():
        if p.name in ex:
            continue
        child_rel = f"{rel_norm}/{p.name}" if rel_norm else p.name
        out.append({"name": p.name, "kind": "dir" if p.is_dir() else "file", "path": child_rel})
    out.sort(key=lambda e: (e["kind"] != "dir", e["name"].lower()))
    return out


def read_text(root, rel: str) -> str:
    """Lit un fichier texte UTF-8 (≤ MAX_BYTES, refuse le binaire). Lève ValueError sinon."""
    target = safe_path(root, rel)
    if not target.is_file():
        raise ValueError(f"pas un fichier : {rel}")
    if target.stat().st_size > MAX_BYTES:
        raise ValueError("fichier trop volumineux")
    data = target.read_bytes()
    if b"\x00" in data:
        raise ValueError("fichier binaire")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError("fichier non UTF-8") from e


def write_text(root, rel: str, content: str) -> None:
    """Écriture atomique (fichier temporaire UUID + replace). Crée les dossiers parents."""
    target = safe_path(root, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8", newline="")
        tmp.replace(target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
