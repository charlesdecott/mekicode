"""Planification : todo-list éphémère (s03), graphe de tâches à dépendances (s07)
et board partagé pour workers autonomes — claim/complete/fail (s11)."""

import json
import threading
from pathlib import Path

from core import STATE_DIR, paint
from tools import register_tool

TODO_FILE: Path = STATE_DIR / "todos.json"
TASKS_FILE: Path = STATE_DIR / "tasks.json"
_TASKS_LOCK = threading.Lock()
_PRIORITY = {"high": 0, "normal": 1, "medium": 1, "low": 2}  # medium toléré (enum source)


# ------------------------------------------------------------------- I/O JSON

def _load(path: Path = TASKS_FILE) -> list:
    """Charge une liste JSON. FIX(mekicode): fichier corrompu → renommé en .bak
    avec avertissement, repart à vide (la source écrasait silencieusement)."""
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        bak = path.with_suffix(path.suffix + ".bak")
        try:
            path.replace(bak)
            print(paint(f"[tasks] {path.name} corrompu ({e}) — sauvegardé en {bak.name}", "yellow"))
        except OSError:
            print(paint(f"[tasks] {path.name} illisible : {e}", "red"))
        return []


def _save(data: list, path: Path = TASKS_FILE) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- todos (s03)

def todo_write(todos: list[dict]) -> str:
    """Écrase la todo-list complète (items {content, status})."""
    items = [t if isinstance(t, dict) else {"content": str(t)} for t in todos]
    items = [{"content": t.get("content", ""), "status": t.get("status", "pending")}
             for t in items]
    _save(items, TODO_FILE)
    lines = "\n".join(f"  [{i}] [{t['status']}] {t['content']}" for i, t in enumerate(items))
    return f"Plan written ({len(items)} tasks):\n{lines}"


def todo_read() -> str:
    todos = _load(TODO_FILE)
    if not todos:
        return "(no todo list found - please use todo_write first)"
    return "\n".join(f"[{i}] [{t['status']:12s}] {t['content']}" for i, t in enumerate(todos))


# ----------------------------------------------------------- graphe de tâches (s07)

def _next_id(tasks: list) -> str:
    """Ids courts t1, t2… (la source utilisait des hex UUID peu lisibles)."""
    nums = [int(t["id"][1:]) for t in tasks
            if str(t.get("id", "")).startswith("t") and str(t["id"])[1:].isdigit()]
    return f"t{max(nums, default=0) + 1}"


def _find(tasks: list, task_id: str) -> dict | None:
    """Id exact, sinon préfixe unique. FIX(mekicode): préfixe vide ou ambigu
    rejeté (la source matchait la première tâche du fichier)."""
    for t in tasks:
        if t["id"] == task_id:
            return t
    pref = [t for t in tasks if task_id and t["id"].startswith(task_id)]
    return pref[0] if len(pref) == 1 else None


def task_add(description: str, deps: list[str] | None = None, priority: str = "normal") -> str:
    with _TASKS_LOCK:
        tasks = _load()
        known = {t["id"] for t in tasks}
        unknown = [d for d in deps or [] if d not in known]
        tid = _next_id(tasks)
        tasks.append({"id": tid, "description": description, "status": "pending",
                      "priority": priority, "depends_on": deps or [], "result": ""})
        _save(tasks)
    warn = f" (warning: unknown deps {unknown})" if unknown else ""
    return f"Created task {tid}: {description}{warn}"


def task_list() -> str:
    tasks = _load()
    if not tasks:
        return "(no tasks currently in the system)"
    return "\n".join(
        f"[{t['id']}] [{t['status']:12s}] [{t.get('priority', 'normal'):6s}]"
        + (f" [needs: {','.join(t['depends_on'])}]" if t.get("depends_on") else "")
        + f" {t['description']}"
        for t in tasks
    )


def task_update(task_id: str, status: str) -> str:
    with _TASKS_LOCK:
        tasks = _load()
        t = _find(tasks, task_id)
        if not t:
            return f"Error: Task with ID '{task_id}' not found."
        t["status"] = status
        _save(tasks)
    return f"Task {t['id']} successfully updated to '{status}'"


def task_complete(task_id: str) -> str:
    return task_update(task_id, "done")


def _next_candidate(tasks: list) -> dict | None:
    """Prochaine tâche pending dont toutes les deps sont done.
    FIX(mekicode): tri high>normal>low puis ordre d'insertion (la source ignorait priority)."""
    done = {t["id"] for t in tasks if t["status"] == "done"}
    ready = [(i, t) for i, t in enumerate(tasks)
             if t["status"] == "pending" and all(d in done for d in t.get("depends_on", []))]
    if not ready:
        return None
    return min(ready, key=lambda it: (_PRIORITY.get(it[1].get("priority", "normal"), 1), it[0]))[1]


def task_next() -> dict | None:
    with _TASKS_LOCK:
        return _next_candidate(_load())


# ------------------------------------------------------- board autonome (s11)

def claim_next_task(agent: str) -> dict | None:
    """Réclame atomiquement la prochaine tâche débloquée (pending → in_progress)."""
    with _TASKS_LOCK:
        tasks = _load()
        t = _next_candidate(tasks)
        if t:
            t["status"], t["claimed_by"] = "in_progress", agent
            _save(tasks)
        return t


def _finish(task_id: str, status: str, key: str, value: str) -> None:
    with _TASKS_LOCK:
        tasks = _load()
        t = _find(tasks, task_id)
        if t:
            t["status"], t[key] = status, value
            _save(tasks)


def complete_task(task_id: str, result: str = "") -> None:
    _finish(task_id, "done", "result", result)


def fail_task(task_id: str, error: str = "") -> None:
    _finish(task_id, "failed", "error", error)


def requeue(task_id: str | None = None) -> int:
    """FIX(mekicode): repasse les failed en pending — re-claimables, le cul-de-sac
    s11 (failed bloquait sa descendance pour toujours) est levé. Retourne le nombre."""
    with _TASKS_LOCK:
        tasks, n = _load(), 0
        for t in tasks:
            if t["status"] == "failed" and task_id in (None, t["id"]):
                t["status"], n = "pending", n + 1
                t.pop("claimed_by", None), t.pop("error", None)
        if n:
            _save(tasks)
    return n


# ------------------------------------------------- outils modèle (à l'import)

register_tool(
    {"name": "todo_write",
     "description": "Write a multi-step todo plan before starting a task. Overwrites the whole list.",
     "input_schema": {"type": "object", "properties": {"todos": {
         "type": "array", "description": "The full todo list (replaces the previous one).",
         "items": {"type": "object", "properties": {
             "content": {"type": "string", "description": "What this step does."},
             "status": {"type": "string", "enum": ["pending", "in_progress", "done"]}},
             "required": ["content"]}}}, "required": ["todos"]}},
    lambda inp: todo_write(inp["todos"]))

register_tool(
    {"name": "todo_read",
     "description": "Read the current todo list to check progress.",
     "input_schema": {"type": "object", "properties": {}}},
    lambda inp: todo_read())

register_tool(
    {"name": "task_add",
     "description": "Create a new task in the persistent dependency graph.",
     "input_schema": {"type": "object", "properties": {
         "description": {"type": "string", "description": "What needs to be done."},
         "depends_on": {"type": "array", "items": {"type": "string"},
                        "description": "List of task IDs this task depends on."},
         "priority": {"type": "string", "enum": ["high", "normal", "low"]}},
         "required": ["description"]}},
    lambda inp: task_add(inp["description"], inp.get("depends_on"),
                         inp.get("priority", "normal")))

register_tool(
    {"name": "task_list",
     "description": "Show all tasks, their IDs, status, and dependency requirements.",
     "input_schema": {"type": "object", "properties": {}}},
    lambda inp: task_list())

register_tool(
    {"name": "task_complete",
     "description": "Mark a task as done (unblocks its dependents).",
     "input_schema": {"type": "object", "properties": {
         "task_id": {"type": "string", "description": "Short ID of the task (e.g. t1)."}},
         "required": ["task_id"]}},
    lambda inp: task_complete(inp["task_id"]))
