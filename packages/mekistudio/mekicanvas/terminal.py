"""terminal.py — node terminal « runner » : lance une commande shell dans le workspace et affiche
la sortie. Non-interactif (pas de PTY) : une commande → sa sortie. L'exécution passe par un thread
(subprocess.run) pour ne pas bloquer la boucle asyncio. cwd confiné au workspace.

Note : c'est l'UTILISATEUR qui lance ces commandes directement (≠ l'agent), donc hors gouvernance s15.
"""
from __future__ import annotations

import asyncio
import subprocess

from nicegui import ui

_TIMEOUT_S = 30


def render_terminal(container, cwd) -> None:
    state = {"out": None}
    with container:
        state["out"] = ui.element("div").classes("term-out")
        with ui.element("div").classes("term-bar"):
            inp = ui.input(placeholder="commande… (Entrée)").props("dense dark borderless").classes("term-in")

    def _emit(text: str, cls: str) -> None:
        with state["out"]:
            ui.label(text if text != "" else " ").classes(cls)
        ui.run_javascript(
            "(()=>{const o=document.querySelector('.node-wrap.focused .term-out')||"
            "document.querySelector('.term-out');if(o)o.scrollTop=o.scrollHeight;})()")

    async def _run(_=None) -> None:
        cmd = (inp.value or "").strip()
        if not cmd:
            return
        inp.value = ""
        _emit("$ " + cmd, "term-cmd")

        def _exec() -> str:
            try:
                r = subprocess.run(cmd, cwd=str(cwd), shell=True, capture_output=True,
                                   text=True, timeout=_TIMEOUT_S)
                return ((r.stdout or "") + (r.stderr or "")).rstrip() or "(aucune sortie)"
            except subprocess.TimeoutExpired:
                return f"[timeout après {_TIMEOUT_S}s]"
            except Exception as e:  # noqa: BLE001
                return f"[erreur] {e}"

        text = await asyncio.get_event_loop().run_in_executor(None, _exec)
        _emit(text, "term-line")

    inp.on("keydown.enter", _run)
