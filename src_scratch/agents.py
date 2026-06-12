"""Agents délégués : subagent éphémère (s04), équipe persistante (s09/s10),
workers autonomes sur le board de tâches (s11).

Équipiers et workers passent par loop.agent_loop (façade sync) : vraie boucle,
vrai dispatch — pas le raccourci « tout tool_use = bash » de s22.
"""

import os
import threading
import time
import uuid
from enum import Enum

from core import paint, text_of
from loop import agent_loop
from mailbox import Mailbox, get_mailbox
from tasks import claim_next_task, complete_task, fail_task
from tools import register_tool


# --- Subagent éphémère (s04) -------------------------------------------------

SUBAGENT_SYSTEM = (
    f"You are a subagent working on a specific subtask at {os.getcwd()}. "
    "Complete your task thoroughly. Summarize your result clearly at the end."
)


def spawn_subagent(task: str, system: str | None = None, tools: list[dict] | None = None) -> str:
    """Boucle isolée à contexte vierge ; seul le texte final remonte au parent."""
    print(paint(f"  [subagent] lancé pour: {task[:60]}…", "magenta"))
    final = agent_loop([{"role": "user", "content": task}],
                       tools=tools, system=system or SUBAGENT_SYSTEM)
    text = text_of(final)
    print(paint(f"  [subagent] terminé: {text[:80]}…", "magenta"))
    return text


register_tool({
    "name": "subagent",
    "description": ("Spawn a fresh subagent to handle a subtask in an isolated context. "
                    "Use for exploration, risky operations, or tasks that shouldn't "
                    "pollute the main conversation history."),
    "input_schema": {
        "type": "object",
        "properties": {"task": {"type": "string",
                                "description": "Detailed instructions for the subagent."}},
        "required": ["task"],
    },
}, sync_fn=lambda inp: spawn_subagent(inp["task"]))


# --- Équipe persistante (s09 + FSM s10) --------------------------------------

TEAMMATES: dict[str, str] = {
    "explorer": (
        f"You are an explorer agent specializing in code comprehension at {os.getcwd()}. "
        "Your goal is to find relevant files, explain logic, and map dependencies. "
        "Use bash, read, glob, and grep to gather intelligence."
    ),
    "writer": (
        f"You are a writer agent specializing in file creation and editing at {os.getcwd()}. "
        "Your goal is to implement features, fix bugs, and document code. "
        "Use write, read, and bash to modify the environment."
    ),
}

_ACTIVE_TEAM: "Team | None" = None  # équipe visée par send_to_teammate


class AgentState(Enum):
    """FSM s10 réduit aux états réellement exercés par la boucle équipier."""
    IDLE = "idle"
    RESPOND = "respond"


class Team:
    """Un thread daemon par équipier ; dialogue par mailbox, états consultables."""

    def __init__(self, teammates: dict[str, str] | None = None):
        self.teammates = teammates or TEAMMATES
        self.mailbox: Mailbox | None = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._states: dict[str, AgentState] = {}

    def start(self, mailbox: Mailbox | None = None) -> None:
        global _ACTIVE_TEAM
        self.mailbox = mailbox or get_mailbox("auto")
        self._stop.clear()
        for name, prompt in self.teammates.items():
            self._states[name] = AgentState.IDLE
            t = threading.Thread(target=self._teammate_loop, args=(name, prompt), daemon=True)
            t.start()
            self._threads.append(t)
        _ACTIVE_TEAM = self
        _register_team_tools(self.teammates)  # enum des destinataires bâti sur l'équipe
        print(paint(f"  [team] démarrée: {', '.join(self.teammates)}", "dim"))

    def stop(self) -> None:
        global _ACTIVE_TEAM
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()
        if _ACTIVE_TEAM is self:
            _ACTIVE_TEAM = None
        print(paint("  [team] arrêtée", "dim"))

    def status(self) -> str:
        if not self._threads:
            return "(équipe arrêtée)"
        return "\n".join(f"- {n}: {s.value}" for n, s in self._states.items())

    def _teammate_loop(self, name: str, prompt: str) -> None:
        # FIX(mekicode): FSM s10 réellement branché sur le flux (code mort dans la source) —
        # IDLE pendant le sondage, RESPOND pendant le traitement, retour IDLE garanti.
        while not self._stop.is_set():
            for msg in self.mailbox.receive(name, timeout=0.5):
                self._states[name] = AgentState.RESPOND
                sender = msg.get("from", "lead")
                print(paint(f"  [{name}] tâche de {sender}: {msg['body'][:60]}…", "magenta"))
                try:
                    reply = text_of(agent_loop([{"role": "user", "content": msg["body"]}],
                                               system=prompt))
                except Exception as e:
                    reply = f"Erreur de l'équipier {name}: {e}"
                finally:
                    self._states[name] = AgentState.IDLE
                self.mailbox.send(sender, name, reply, req_id=msg.get("req_id"))
                print(paint(f"  [{name}] réponse envoyée à {sender}", "magenta"))


def send_to_teammate(name: str, message: str, timeout: float = 120) -> str:
    """Délègue à un équipier et bloque jusqu'à sa réponse, corrélée par req_id."""
    team = _ACTIVE_TEAM
    if team is None or team.mailbox is None:
        return "Erreur: aucune équipe active (appeler Team().start() d'abord)."
    if name not in team.teammates:
        return f"Erreur: '{name}' n'est pas un équipier connu."
    req_id = uuid.uuid4().hex[:8]
    team.mailbox.send(name, "lead", message, req_id=req_id)
    print(paint(f"  [lead] attend la réponse de {name}…", "dim"))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for r in team.mailbox.receive("lead", timeout=1.0):
            if r.get("req_id") == req_id:
                return f"Réponse de {r.get('from', name)}:\n{r['body']}"
            # FIX(mekicode): réponse tardive d'une requête expirée → JETÉE (s09 la
            # drainait et la présentait comme la réponse de l'appel suivant)
            print(paint(f"  [lead] réponse tardive de {r.get('from', '?')} ignorée "
                        f"(req_id {r.get('req_id')} ≠ {req_id})", "yellow"))
    return f"Timeout: '{name}' n'a pas répondu en {timeout:.0f} s."


def _register_team_tools(teammates: dict[str, str]) -> None:
    """Outils du lead, enregistrés au start() (l'enum dépend de l'équipe réelle)."""
    register_tool({
        "name": "send_to_teammate",
        "description": "Delegate a subtask to a specialist teammate. This blocks until they reply.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "enum": list(teammates)},
                "message": {"type": "string", "description": "Specific tasks/instructions."},
            },
            "required": ["name", "message"],
        },
    }, sync_fn=lambda inp: send_to_teammate(inp["name"], inp["message"]))
    register_tool({
        "name": "list_teammates",
        "description": "List all currently available specialist agents and their roles.",
        "input_schema": {"type": "object", "properties": {}},
    }, sync_fn=lambda inp: "\n".join(f"- {n}: {p[:80]}…" for n, p in teammates.items()))


# --- Workers autonomes (s11) --------------------------------------------------

def run_autonomous_agent(name: str, max_idle: int = 3) -> None:
    """Cycle s11 : claim → agent_loop → complete/fail ; stop après max_idle tours vides."""
    system = (f"You are autonomous worker agent '{name}' at {os.getcwd()}. "
              "Process the claimed task thoroughly and correctly. "
              "Use your tools to achieve the task description provided.")
    print(paint(f"  [{name}] en ligne — sondage du board", "dim"))
    idle = 0
    while idle < max_idle:
        task = claim_next_task(name)
        if task is None:
            idle += 1
            time.sleep(1.0)
            continue
        idle = 0
        print(paint(f"  [{name}] réclame [{task['id']}] {task['description'][:60]}…", "magenta"))
        try:
            # FIX(mekicode): vraie boucle + vrai dispatch (s22 exécutait tout tool_use comme bash)
            final = agent_loop([{"role": "user", "content": task["description"]}], system=system)
            complete_task(task["id"], text_of(final))
            print(paint(f"  [{name}] terminé: {task['id']}", "green"))
        except Exception as e:
            fail_task(task["id"], str(e))
            print(paint(f"  [{name}] échec: {task['id']} — {e}", "red"))
    print(paint(f"  [{name}] arrêt après {max_idle} tours sans tâche", "dim"))


def start_workers(n: int = 2) -> list[threading.Thread]:
    """Lance n workers autonomes en threads daemon."""
    threads = []
    for i in range(n):
        t = threading.Thread(target=run_autonomous_agent, args=(f"worker-{i + 1}",), daemon=True)
        t.start()
        threads.append(t)
    return threads
