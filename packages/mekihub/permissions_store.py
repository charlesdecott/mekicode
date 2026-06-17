"""permissions_store.py — surcharges de permission persistées par projet.

Fichier : <base>/permissions/<project_id>.yaml, même schéma 3 tiers que mekicore.
Couche projet de la résolution en couches (session = RAM ; projet = ici ; global = mekicore).
"""
from __future__ import annotations

from pathlib import Path

import yaml

_TIERS = ("always_deny", "always_allow", "ask_user")
_DEFAULT_BASE = Path.cwd() / ".mekicode"


def _path(project_id: str, base_dir: Path | None) -> Path:
    base = base_dir or _DEFAULT_BASE
    return base / "permissions" / f"{project_id}.yaml"


def load_project_overrides(project_id: str, *, base_dir: Path | None = None) -> dict:
    p = _path(project_id, base_dir)
    if not p.exists():
        return {tier: [] for tier in _TIERS}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    perms = data.get("permissions") or {}
    return {tier: list(perms.get(tier) or []) for tier in _TIERS}


def add_project_rule(project_id: str, tier: str, pattern: str, reason: str,
                     *, base_dir: Path | None = None) -> None:
    assert tier in _TIERS, tier
    cur = load_project_overrides(project_id, base_dir=base_dir)
    if not any(r.get("pattern") == pattern for r in cur[tier]):
        cur[tier].append({"pattern": pattern, "reason": reason})
    p = _path(project_id, base_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"permissions": cur}, allow_unicode=True), encoding="utf-8")
