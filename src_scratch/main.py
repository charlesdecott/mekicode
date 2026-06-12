"""main.py — LE point d'entrée du harness : REPL unifié, toutes features actives.

Un seul asyncio.run pour toute la session (pattern s18) : le runtime MCP, la
boucle d'agent et les commandes partagent la même event loop ; seules les
saisies utilisateur partent dans un thread (asyncio.to_thread). Les équipiers,
workers et worktrees tournent dans leurs propres threads via la façade sync
loop.agent_loop.

Usage : python main.py [--seq] [--no-cache] [--mcp] [--backend auto|jsonl|queue|redis]
"""
import argparse
import asyncio

import agents
import context
import mcp_runtime
import sessions
import tasks
import worktree
from core import DEFAULT_SYSTEM, emit, paint, text_of
from loop import CACHE, INTERRUPTS, agent_loop_async
from mailbox import get_mailbox

HELP = """Commandes :
  :sessions             liste les sessions sauvegardées
  :resume <id>          reprend une session       :fork <id>   la duplique
  :title <texte>        renomme la session        :save        sauvegarde manuelle
  :todos / :tasks       plan courant / graphe de tâches persistant
  :requeue              repasse les tâches failed en pending
  :team on|off|status   équipiers persistants (explorer, writer)
  :workers <n>          n workers autonomes sur le board de tâches
  :wt <t1> | <t2> ...   exécute chaque tâche dans un worktree git isolé
  :compact              force la compaction du contexte
  :cache / :mcp         stats de cache / état des serveurs MCP
  :help / :quit         cette aide / quitter (Ctrl+C pendant un tour = interruption)"""


def build_system() -> str:
    """Prompt système assemblé : base + mémoire persistante + index des skills + rappel todo."""
    parts = [DEFAULT_SYSTEM]
    memory = context.load_memory()
    if memory:
        parts.append("## Memory from previous sessions\n" + memory[-4000:])
    parts.append("## Available skills (use the load_skill tool before specialized tasks)\n"
                 + context.skills_index())
    parts.append("For multi-step work, write a plan with todo_write first and keep it updated.")
    return "\n\n".join(parts)


def _repair(messages: list) -> None:
    """Après une interruption/erreur en plein tour : retire un éventuel message
    assistant final contenant des tool_use sans tool_result (l'API le refuserait)."""
    if messages and messages[-1]["role"] == "assistant" and any(
            getattr(b, "type", None) == "tool_use" or
            (isinstance(b, dict) and b.get("type") == "tool_use")
            for b in messages[-1]["content"] or []):
        messages.pop()


async def handle_command(cmd: str, state: dict, args) -> None:
    """Exécute une commande ':' — state = {messages, sid, team}."""
    verb, _, rest = cmd.partition(" ")
    rest = rest.strip()
    if verb == ":help":
        print(HELP)
    elif verb == ":sessions":
        print(sessions.list_sessions())
    elif verb in (":resume", ":fork") and rest:
        sid = sessions.fork_session(rest) if verb == ":fork" else rest
        state["messages"], meta = sessions.load_session(sid)
        state["sid"] = sid
        print(paint(f"[session] {sid} — « {meta['title']} », {meta['turns']} messages", "cyan"))
    elif verb == ":title" and rest:
        state["sid"] = sessions.save_session(state["messages"], state["sid"], title=rest)
        print(paint(f"[session] renommée : {rest}", "dim"))
    elif verb == ":save":
        state["sid"] = sessions.save_session(state["messages"], state["sid"])
        print(paint(f"[session] sauvegardée : {state['sid']}", "dim"))
    elif verb == ":todos":
        print(tasks.todo_read())
    elif verb == ":tasks":
        print(tasks.task_list())
    elif verb == ":requeue":
        print(paint(f"[tasks] {tasks.requeue()} tâche(s) repassée(s) en pending", "dim"))
    elif verb == ":team":
        if rest == "on" and state["team"] is None:
            state["team"] = agents.Team()
            state["team"].start(get_mailbox(args.backend))
        elif rest == "off" and state["team"] is not None:
            state["team"].stop()
            state["team"] = None
        else:
            print(state["team"].status() if state["team"] else "(équipe arrêtée — :team on)")
    elif verb == ":workers":
        n = int(rest or "2")
        agents.start_workers(n)
        print(paint(f"[workers] {n} worker(s) autonome(s) sur le board (:tasks pour suivre)", "dim"))
    elif verb == ":wt" and rest:
        jobs = [t.strip() for t in rest.split("|") if t.strip()]
        results = await asyncio.to_thread(worktree.run_parallel_tasks, jobs)
        for r in results:
            print(f"  [{r['id']}] {r['status']} — fichiers : {', '.join(r['files']) or '(aucun)'}")
    elif verb == ":compact":
        state["messages"][:] = context.maybe_compact(state["messages"], force=True)
    elif verb == ":cache":
        print(CACHE.summary())
    elif verb == ":mcp":
        if mcp_runtime.HAS_MCP and not mcp_runtime.MCP_SESSIONS:
            await mcp_runtime.start_mcp()
        print(mcp_runtime.mcp_status())
    else:
        print(paint(f"commande inconnue ou incomplète : {cmd} (:help)", "yellow"))


async def repl(args) -> None:
    state: dict = {"messages": [], "sid": None, "team": None}
    INTERRUPTS.install()
    emit("session_start", {"args": vars(args)})
    if args.mcp:
        await mcp_runtime.start_mcp()
    system = build_system()
    print(paint("mekicode src_scratch — harness complet (s01–s23). :help pour les commandes.", "cyan"))
    try:
        while True:
            try:
                raw = await asyncio.to_thread(input, paint("\nyou> ", "green"))
            except (EOFError, KeyboardInterrupt):
                break
            user = raw.lstrip("﻿").strip()  # BOM d'un pipe PowerShell éventuel
            if not user:  # FIX(mekicode) s17 : l'entrée vide partait à l'API (erreur content:"")
                continue
            if user in (":quit", ":q", ":exit"):
                break
            if user.startswith(":"):
                await handle_command(user, state, args)
                continue
            emit("user_message", {"text": user})
            state["messages"].append({"role": "user", "content": user})
            try:
                final = await agent_loop_async(state["messages"], system=system,
                                               parallel=not args.seq, cache=not args.no_cache)
                emit("assistant_message", {"text": text_of(final)})
            except KeyboardInterrupt:
                print(paint("\n[interrompu] tour abandonné — l'historique reste cohérent", "red"))
                _repair(state["messages"])
            except Exception as e:
                print(paint(f"\n[erreur] {e}", "red"))
                _repair(state["messages"])
            state["messages"][:] = context.maybe_compact(state["messages"])
            state["sid"] = sessions.save_session(state["messages"], state["sid"])  # auto-save s17
    finally:
        if state["team"]:
            state["team"].stop()
        await mcp_runtime.stop_mcp()
        emit("session_end", {"sid": state["sid"]})
        if not args.no_cache and CACHE.calls:
            print(paint(CACHE.summary(), "dim"))
        if state["sid"]:
            print(paint(f"[session] {state['sid']} sauvegardée — :resume {state['sid']}", "dim"))


def main() -> None:
    p = argparse.ArgumentParser(description="Harness src_scratch — REPL unifié")
    p.add_argument("--seq", action="store_true", help="dispatch séquentiel (défaut: parallèle)")
    p.add_argument("--no-cache", action="store_true", help="désactive le prompt caching")
    p.add_argument("--mcp", action="store_true", help="démarre les serveurs MCP du config.yaml")
    p.add_argument("--backend", default="auto", choices=["auto", "jsonl", "queue", "redis"],
                   help="backend des mailboxes d'équipe")
    args = p.parse_args()
    if args.mcp and args.seq:
        # Les outils MCP sont async-only (liés à l'event loop) : le mode --seq les casserait.
        print(paint("[main] --mcp force le dispatch parallèle (outils MCP async)", "yellow"))
        args.seq = False
    try:
        asyncio.run(repl(args))
    except KeyboardInterrupt:
        print(paint("\nbye", "dim"))


if __name__ == "__main__":
    main()
