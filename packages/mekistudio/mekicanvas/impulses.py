"""impulses.py — mappe un event d'outil (nos hooks) -> intent d'impulsion canvas.

Porté de chat-impulses.js (impulseFor). PUR. Seuls les outils de LECTURE déclenchent une
comète ; les écritures / bash ne produisent rien (UX silencieuse, comme l'amont).
Adapté à NOS outils minuscules : READ_TOOLS = {read, grep, glob}.
"""
from __future__ import annotations

READ_TOOLS = {"read", "grep", "glob"}


def normalize_path(p: str) -> str:
    if not p:
        return ""
    p = p.replace("\\", "/")
    while "//" in p:
        p = p.replace("//", "/")
    while p.startswith("./"):        # retire un PRÉFIXE "./" (pas les caractères : préserve ".env")
        p = p[2:]
    return p.rstrip("/")


def impulse_for(event: dict) -> dict | None:
    if not event:
        return None
    t = event.get("type")
    if t == "tool_result":
        if event.get("is_error"):
            return {"kind": "glow", "target": {"by": "kind", "value": "chat"}, "level": "error"}
        name = (event.get("name") or "").lower()
        if name not in READ_TOOLS:
            return None
        fp = event.get("file_path")
        if fp:
            return {
                "kind": "comet", "target": {"by": "file", "value": fp}, "level": "strong",
                "fallback": {"kind": "comet", "target": {"by": "kind", "value": "fileexplorer"},
                             "level": "strong"},
            }
        return {"kind": "comet", "target": {"by": "kind", "value": "fileexplorer"}, "level": "soft"}
    if t == "turn_end":
        return {"kind": "glow", "target": {"by": "kind", "value": "chat"}, "level": "strong",
                "dismissable": True}
    return None


def impulse_from_hub_event(event) -> dict | None:
    """Adapte un event mekihub déjà enrichi -> impulse_for().

    `event` est attendu avec, pour ToolFinished, un attribut `args` (dict) injecté par
    l'appelant (le canvas garde une table id->args depuis ToolStarted, cf. canvas_page).
    """
    name = type(event).__name__
    if name == "ToolFinished":
        args = getattr(event, "args", None) or {}
        out = str(getattr(event, "output", ""))
        is_error = out.startswith("Error") or "Denied" in out
        fp = normalize_path(args.get("path", "")) or None
        return impulse_for({"type": "tool_result", "name": getattr(event, "name", ""),
                            "file_path": fp, "is_error": is_error})
    if name == "RunError":
        return impulse_for({"type": "tool_result", "is_error": True})
    if name in ("RunFinished", "Idle"):
        return impulse_for({"type": "turn_end"})
    return None
