"""s15 — Équipes d'agents : le Lead et ses coéquipiers persistants.

Démo du sous-système teams de shared.py, porté de
inspiration/learn-claude-code/s15_agent_teams/code.py :

- MessageBus / BUS     : mailboxes JSONL append-only sous .mailboxes/,
  lecture DESTRUCTIVE (read_inbox = read_text + unlink) ;
- spawn_teammate_thread : un mini-harness complet par teammate (thread
  daemon, 8 outils, gate d'approbation de plan, idle_poll) — exposé au Lead
  via le wrapper run_spawn_teammate ;
- wrappers lead        : run_spawn_teammate, run_send_message (expéditeur
  'lead' codé en dur), run_check_inbox (drainage + routage protocole).

L'original recopiait 929 lignes ; ici tout vient de shared.py et ce fichier
ne garde que le câblage des outils du Lead + l'injection passive de l'inbox
en fin de tour (le point clé de s15 : les messages des teammates ENTRENT
dans l'historique du Lead). Démo hors-ligne : `bus`. Lancement :
python src/sessions/s15.py
"""
import _bootstrap  # noqa: F401 — rend shared.py importable depuis sessions/
import shared  # gardé : main() rebinde shared.CLI_ACTIVE (doit passer par le module)
from shared import (
    BUILTIN_HANDLERS, BUILTIN_TOOLS, BUS, MAILBOX_DIR, PROMPT, WORKDIR,
    active_teammates, agent_loop, print_turn_assistants,
)


def pick(*names):
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("spawn_teammate", "send_message", "check_inbox",
              "create_task", "list_tasks", "bash")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {n: BUILTIN_HANDLERS[n] for n in TOOL_NAMES}
SYSTEM = ("You are 'lead', coordinating a team. spawn_teammate starts a "
          "persistent autonomous agent (its results arrive in your inbox); "
          "send_message talks to a teammate; check_inbox drains your inbox. "
          "Teammates can claim tasks you create with create_task. "
          f"Workspace: {WORKDIR}.")


def demo_bus():
    """Hors-ligne : envoi = append d'une ligne JSON dans {dest}.jsonl ;
    lecture = consommation (le fichier est supprimé). Observable sur disque
    entre les deux."""
    BUS.send("alice", "lead", "Schéma terminé : tables users+sessions")
    BUS.send("bob", "lead", "Tests rouges sur /login", "result")
    inbox_file = MAILBOX_DIR / "lead.jsonl"
    lines = len(inbox_file.read_text().splitlines())
    print(f"  sur disque : {inbox_file} ({lines} lignes JSONL)")
    for m in BUS.read_inbox("lead"):
        print(f"  [{m['from']}] ({m['type']}) {m['content']}")
    print(f"  relecture destructive -> {BUS.read_inbox('lead')} "
          "(le fichier a été consommé)")


def drain_lead_inbox(history: list):
    """Canal passif de s15 : en fin de tour, l'inbox du Lead est injectée
    dans l'historique comme message user [Inbox] — le LLM y réagira au tour
    suivant (le canal actif étant l'outil check_inbox en plein tour)."""
    msgs = BUS.read_inbox("lead")
    if not msgs:
        return
    text = "\n".join(f"From {m['from']} ({m['type']}): {m['content'][:200]}"
                     for m in msgs)
    history.append({"role": "user", "content": f"[Inbox]\n{text}"})
    print(f"  [inbox : {len(msgs)} message(s) injecté(s) dans l'historique]")


def main():
    # Les teammates parlent depuis leurs threads : terminal_print doit
    # redessiner la ligne de saisie en cours.
    shared.CLI_ACTIVE = True
    print("s15 — équipes d'agents. "
          "`bus`, `who`, ou un prompt LLM (ex. spawn). `q` pour quitter.")
    history = []
    while True:
        try:
            user = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user.lower() in ("q", "quit", "exit"):
            break
        if not user:
            continue
        if user == "bus":
            demo_bus()
            continue
        if user == "who":
            names = list(active_teammates) or ["(aucun teammate actif)"]
            print("  " + ", ".join(names))
            continue
        turn_start = len(history)
        agent_loop(user, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)
        drain_lead_inbox(history)


if __name__ == "__main__":
    main()
