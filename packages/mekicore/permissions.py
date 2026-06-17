"""permissions.py — gouvernance s15, 3 tiers + résolution en couches.

Ordre d'évaluation (court-circuit) : always_deny -> always_allow -> ask_user -> ALLOW.
Résolution en couches : on fusionne `overrides` (session puis projet) EN TÊTE de chaque
tier, AVANT les règles globales. Une surcharge `always_allow` d'un motif l'emporte donc
sur un `ask_user` global (et `always_deny` l'emporte sur tout).

`check_permission` est PUR (aucune I/O, aucun input()). Le tier ASK est juste signalé ;
c'est l'appelant (mekihub) qui orchestre la demande asynchrone à l'utilisateur.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ALLOW = "allow"
DENY = "deny"
ASK = "ask"

_TIERS = ("always_deny", "always_allow", "ask_user")
_RULES_PATH = Path(__file__).resolve().parent / "permissions.yaml"


@dataclass
class Decision:
    kind: str          # ALLOW | DENY | ASK
    reason: str = ""


def load_rules(path: Path | None = None) -> dict:
    """Section `permissions` du YAML — 3 tiers, listes vides par défaut."""
    p = path or _RULES_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    perms = data.get("permissions") or {}
    return {tier: list(perms.get(tier) or []) for tier in _TIERS}


def _merge(base: dict, overrides: dict | None) -> dict:
    """Fusionne overrides EN TÊTE de chaque tier (priorité aux surcharges)."""
    if not overrides:
        return base
    return {
        tier: list(overrides.get(tier) or []) + list(base.get(tier) or [])
        for tier in _TIERS
    }


def _hit(rules_tier: list, text: str) -> dict | None:
    for rule in rules_tier:
        if re.search(rule["pattern"], text, re.IGNORECASE):
            return rule
    return None


def check_permission(
    tool: str, input_str: str, rules: dict, *, overrides: dict | None = None
) -> Decision:
    """Décision pour un appel d'outil. Pur, sans effet de bord."""
    eff = _merge(rules, overrides)
    r = _hit(eff["always_deny"], input_str)
    if r:
        return Decision(DENY, f"Denied: {r.get('reason', 'blocked by policy')}")
    if _hit(eff["always_allow"], input_str):
        return Decision(ALLOW)
    r = _hit(eff["ask_user"], input_str)
    if r:
        return Decision(ASK, r.get("reason", "requires user confirmation"))
    return Decision(ALLOW)


def make_permission_hook(rules, ask_resolver, *, overrides_provider=None):
    """Fabrique un abonné `pre_tool` du HookBus.

    - `rules` : dict 3 tiers (load_rules()).
    - `ask_resolver(tool, target, reason) -> bool` : BLOQUANT. True si autorisé.
      (mekihub fournit un resolver qui publie PermissionRequested + attend la décision.)
    - `overrides_provider() -> dict | None` : surcharges courantes (session+projet fusionnées).

    Renvoie une fonction hook(payload) -> str|None (raison de refus, ou None).
    """
    def hook(payload: dict) -> "str | None":
        tool = payload.get("tool", "")
        tool_input = payload.get("input") or {}
        target = str(next(iter(tool_input.values()), "")) if tool_input else ""
        ov = overrides_provider() if overrides_provider else None
        d = check_permission(tool, target, rules, overrides=ov)
        if d.kind == DENY:
            return d.reason
        if d.kind == ASK:
            allowed = ask_resolver(tool, target, d.reason)
            return None if allowed else f"Denied: refusé par l'utilisateur ({d.reason})"
        return None

    return hook
