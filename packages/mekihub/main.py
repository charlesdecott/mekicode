#!/usr/bin/env python3
"""main.py — entrypoint mekihub : hub + adaptateurs activés par .env (front/discord on/off).

MEKIHUB_FRONT=on|off   lance le front NiceGUI (in-process)
MEKIHUB_DISCORD=on|off lance l'adaptateur Discord (nécessite DISCORD_BOT_TOKEN)
Headless possible : MEKIHUB_FRONT=off MEKIHUB_DISCORD=on
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                 # session, events, hub
sys.path.insert(0, str(HERE.parent))          # packages/ (mekillm, mekihub)
sys.path.insert(0, str(HERE.parent / "mekicore"))  # base, tools, events de mekicore


def build_hub():
    """Construit un SessionHub câblé sur mekillm + les outils de mekicore."""
    import mekillm
    import tools as core_tools
    from hub import SessionHub
    from session import SessionStore
    from projects import ProjectRegistry
    reg = ProjectRegistry(); reg.ensure_default()
    return SessionHub(store=SessionStore(), llm_factory=mekillm.LLM, tools=core_tools.TOOLS,
                      dispatch_factory=core_tools.make_dispatch, registry=reg)


def main() -> None:
    front = os.environ.get("MEKIHUB_FRONT", "on").lower() != "off"
    discord_on = os.environ.get("MEKIHUB_DISCORD", "off").lower() == "on"
    if discord_on and not front:
        # headless : boucle asyncio Discord seule (provisioning + miroir bidirectionnel)
        import asyncio
        from adapters.discord import run_discord
        hub = build_hub()
        token = os.environ["DISCORD_BOT_TOKEN"]
        asyncio.run(run_discord(
            hub, hub.registry, hub.store, token=token,
            guild_id=os.environ.get("DISCORD_GUILD_ID") or None,
            admin_user_id=os.environ.get("MEKICODE_ADMIN_USER_ID") or None,
        ))
        return
    # front activé : déléguer à l'app NiceGUI (qui crée son propre hub module-level)
    sys.path.insert(0, str(HERE.parent / "mekichat"))
    import app  # noqa: F401  (app.py appelle ui.run sous son garde __main__)
    print("mekihub: front mekichat — lancer via `python packages/mekichat/app.py`")


if __name__ in {"__main__", "__mp_main__"}:
    main()
