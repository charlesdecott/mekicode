#!/usr/bin/env python3
"""main.py — REPL de mekicore : le s01 de claude-code-from-scratch branché sur mekillm."""
from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap : rend `import mekillm` résoluble en lancement direct (ajoute packages/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mekillm  # noqa: E402
from base import agent_loop  # noqa: E402
from tools import DISPATCH, TOOLS  # noqa: E402

SYSTEM = f"You are a coding agent at {Path.cwd()}. Use tools to solve tasks. Act, don't explain."


def main() -> None:
    """REPL : lit une requête, lance la boucle agent, recommence."""
    print("\033[90mmekicore: one loop + bash = an agent (LLM via mekillm)\033[0m\n")
    llm = mekillm.LLM()
    messages = [{"role": "system", "content": SYSTEM}]
    while True:
        try:
            query = input("\033[36mmekicore >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting session.")
            return
        if not query or query.lower() in ("q", "exit", "quit"):
            print("Goodbye.")
            return
        messages.append({"role": "user", "content": query})
        agent_loop(messages, llm, TOOLS, DISPATCH)
        print()


if __name__ == "__main__":
    main()
