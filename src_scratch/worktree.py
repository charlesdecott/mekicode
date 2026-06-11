"""Worktrees git jetables — isolation des tâches parallèles (cycle de vie s23).

Chaque tâche reçoit une branche ``task/<id>`` et un répertoire frère du dépôt
(``../.worktree-<id>``) où tourne un agent_loop dédié ; le travail est commité,
les fichiers touchés relevés, puis tout est démonté (try/finally garanti).

Limite documentée : ``os.chdir`` est GLOBAL au process et les outils (bash,
read, write…) résolvent leurs chemins relatifs au moment de l'appel. Le
sandwich chdir → agent_loop → restore est donc protégé par un verrou
module-level : les tâches « parallèles » sérialisent leur phase d'exécution
d'agent (setup, teardown git et analyse restent concurrents). On privilégie
l'isolation garantie au parallélisme réel — l'éliminer demanderait de passer
le répertoire explicitement à chaque outil.
"""
import os
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from core import paint
from loop import agent_loop

# FIX(mekicode): cwd figé à l'import — pendant le sandwich chdir d'un autre
# thread, os.getcwd() pointerait dans SON worktree et les commandes git du
# dépôt principal viseraient le mauvais répertoire.
_REPO_CWD = os.getcwd()
_CHDIR_LOCK = threading.Lock()  # sérialise les fenêtres chdir (global au process)


def _git(*args: str, cwd: str | None = None) -> tuple[bool, str]:
    """Exécute ``git <args>`` ; retourne (succès, stdout — ou stderr si échec)."""
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd or _REPO_CWD)
    ok = r.returncode == 0
    return ok, (r.stdout.strip() if ok else r.stderr.strip() or r.stdout.strip())


def create_worktree(task_id: str) -> tuple[str, str]:
    """Crée la paire branche ``task/<id>`` + worktree frère du dépôt.

    Sanitise le nom, suffixe en cas de branche homonyme, avertit si l'arbre
    est sale, refuse le detached HEAD. Lève RuntimeError en cas d'échec.
    """
    ok, root = _git("rev-parse", "--show-toplevel")
    if not ok:
        raise RuntimeError("pas un dépôt git")
    if not _git("symbolic-ref", "--short", "HEAD")[0]:
        raise RuntimeError("HEAD détaché : checkout une branche avant de lancer des tâches")
    if _git("status", "--porcelain")[1]:
        print(paint("  [worktree] arbre sale : la branche forke du dernier commit, "
                    "les modifs non commitées n'y seront pas", "yellow"))
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", task_id)[:40]
    # FIX(mekicode): branche homonyme → suffixe -2, -3… (s23 détruisait la branche
    # préexistante via branch -D, y compris une éventuelle branche de travail humaine)
    branch, n = f"task/{safe}", 1
    while _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")[0]:
        n += 1
        branch = f"task/{safe}-{n}"
    suffix = "" if n == 1 else f"-{n}"
    # hors du dépôt : un worktree interne polluerait status et les globs des agents
    path = str(Path(root).parent / f".worktree-{safe[:20]}{suffix}")
    if Path(path).exists():  # reste d'un run crashé → nettoyage préventif
        _git("worktree", "remove", "--force", path)
        shutil.rmtree(path, ignore_errors=True)
    ok, err = _git("worktree", "add", "-b", branch, path)
    if not ok:
        raise RuntimeError(f"création du worktree échouée : {err}")
    print(paint(f"  [worktree] {path} (branche {branch})", "dim"))
    return path, branch


def remove_worktree(path: str, branch: str, keep_branch: bool = False) -> None:
    """Démonte worktree, répertoire et branche (sauf keep_branch).

    Tolérant : chaque étape tente sa part, aucune ne bloque les autres.
    """
    _git("worktree", "remove", "--force", path)
    if Path(path).exists():  # rattrapage (verrous Windows, etc.)
        shutil.rmtree(path, ignore_errors=True)
    if branch and not keep_branch:
        _git("branch", "-D", branch)
    _git("worktree", "prune")  # purge les métadonnées si remove a échoué avant rmtree


def prune_stale() -> int:
    """Purge les worktrees dont le répertoire a disparu (crashs). Retourne le compte."""
    ok, root = _git("rev-parse", "--show-toplevel")
    if not ok:
        return 0
    count = 0
    for line in _git("worktree", "list", "--porcelain")[1].splitlines():
        if line.startswith("worktree "):
            p = line[9:]
            if p != root and not Path(p).exists():
                _git("worktree", "remove", "--force", p)
                count += 1
    _git("worktree", "prune")
    return count


def run_task_in_worktree(task: str, task_id: str | None = None) -> dict:
    """Cycle de vie complet d'une tâche isolée.

    worktree → agent_loop dédié (sandwich chdir sous verrou) → commit du
    travail → relevé des fichiers touchés → nettoyage garanti (try/finally).
    Retourne {id, task, status, result, error, files}.
    """
    tid = task_id or f"T-{uuid.uuid4().hex[:6]}"
    res: dict = {"id": tid, "task": task, "status": "failed", "result": "", "error": "", "files": []}
    try:
        path, branch = create_worktree(tid)
    except Exception as e:
        res["error"] = str(e)
        print(paint(f"  [{tid}] setup échoué : {e}", "red"))
        return res
    base = _git("rev-parse", "HEAD", cwd=path)[1]  # point de fork, pour le diff final
    try:
        system = (f"Tu es un agent de code dans le worktree isolé {path}. "
                  f"Objectif : {task}. Résume tes changements à la fin.")
        with _CHDIR_LOCK:  # voir docstring module : fenêtre chdir sérialisée
            old = os.getcwd()
            try:
                os.chdir(path)
                final = agent_loop([{"role": "user", "content": task}], system=system)
            finally:
                os.chdir(old)
        res["result"] = "".join(getattr(b, "text", "") for b in final.content)
        if _git("status", "--porcelain", cwd=path)[1]:  # commit, sinon le diff ne voit rien
            _git("add", "-A", cwd=path)
            _git("commit", "-m", f"[{tid}] {task[:60]}", cwd=path)
        # FIX(mekicode): fichiers touchés relevés AVANT la suppression de la branche
        # (s23 lançait l'analyse après le teardown : le branch -D la neutralisait)
        ok, out = _git("diff", "--name-only", base, branch)
        res["files"] = out.splitlines() if ok and out else []
        res["status"] = "done"
        print(paint(f"  [{tid}] terminé", "green"))
    except Exception as e:
        res["error"] = str(e)
        print(paint(f"  [{tid}] échec : {e}", "red"))
    finally:
        remove_worktree(path, branch)  # nettoyage garanti, succès ou crash
    return res


def run_parallel_tasks(tasks: list[str]) -> list[dict]:
    """Une tâche par thread/worktree, puis détection des fichiers touchés par ≥ 2 tâches."""
    pruned = prune_stale()
    if pruned:
        print(paint(f"  [worktree] {pruned} worktree(s) périmé(s) purgé(s)", "dim"))
    results: list[dict] = [{} for _ in tasks]

    def _worker(i: int, desc: str) -> None:
        results[i] = run_task_in_worktree(desc, task_id=f"T-{i + 1}")

    threads = [threading.Thread(target=_worker, args=(i, d), daemon=True)
               for i, d in enumerate(tasks)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    done = [r for r in results if r.get("status") == "done"]
    for i, a in enumerate(done):  # intersections paire à paire sur les diffs déjà relevés
        for b in done[i + 1:]:
            common = sorted(set(a["files"]) & set(b["files"]))
            if common:
                msg = f"{a['id']} <-> {b['id']} : {', '.join(common[:5])}"
                print(paint(f"  [conflit] {msg}", "yellow"))
                a.setdefault("conflicts", []).append(msg)
                b.setdefault("conflicts", []).append(msg)
    return results
