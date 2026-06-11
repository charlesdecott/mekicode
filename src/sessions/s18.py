"""s18 · Isolation par worktree — un répertoire et une branche par tâche.

Concept : en s17, Alice et Bob travaillent dans le même répertoire et
s'écrasent mutuellement leurs fichiers. s18 répond avec `git worktree` :
plusieurs répertoires de travail indépendants sur un même dépôt, chacun sur
sa branche `wt/{nom}`. La liaison est minimale — un champ `worktree` sur la
tâche (bind_task_to_worktree), qui NE change PAS son statut : elle reste
pending, et c'est l'auto-claim de s17 qui basculera les outils fichiers du
teammate dans ce répertoire. Cycle de vie complet : create_worktree (nom
validé AVANT git), remove_worktree (refus par défaut s'il reste des
changements), keep_worktree (conserver pour revue), journal events.jsonl.

Mapping vers l'original (inspiration/learn-claude-code/s18_worktree_isolation/
code.py) : validate_worktree_name, run_git, log_event, create_worktree,
bind_task_to_worktree, remove_worktree, keep_worktree, le champ Task.worktree
et le paramètre cwd des outils fichiers vivent dans shared.py. Délta ici :
une démo NON DESTRUCTIVE — un dépôt git jetable est créé dans un répertoire
temporaire AVANT l'import de shared (shared.WORKDIR = Path.cwd() est figé à
l'import), tout le cycle de vie s'y déroule, rien n'est touché dans le
projet ; sans git utilisable, la démo affiche les messages d'erreur clairs
retournés par shared.
"""

import os
import shutil
import subprocess
import tempfile
import _bootstrap  # noqa: F401 — rend shared.py importable depuis sessions/

def _setup_demo_repo():
    """Crée un dépôt git jetable (avec un commit initial : `git worktree add
    ... HEAD` l'exige) et s'y place. Doit s'exécuter AVANT l'import de
    shared, car shared fige WORKDIR sur Path.cwd() au moment de l'import."""
    try:
        repo = tempfile.mkdtemp(prefix="s18_worktrees_")
        def git(*args):
            subprocess.run(["git", "-C", repo, *args], check=True,
                           capture_output=True, timeout=30)
        git("init", "-q")
        git("-c", "user.name=mekicode", "-c", "user.email=demo@mekicode",
            "commit", "--allow-empty", "-m", "init", "-q")
        os.chdir(repo)
        return repo
    except Exception as e:
        print(f"[s18] pas de dépôt de test ({e}) — la démo montrera les "
              "messages d'erreur de shared faute de repo git.")
        return None


DEMO_REPO = _setup_demo_repo()
from shared import (  # noqa: E402 — doit voir le cwd du dépôt de test
    WORKDIR, WORKTREES_DIR, bind_task_to_worktree, create_task,
    create_worktree, keep_worktree, load_task, remove_worktree,
    validate_worktree_name)


def _cleanup():
    """Supprime le dépôt jetable (les objets git sont en lecture seule sous
    Windows, d'où le rétablissement des droits à la volée)."""
    if not DEMO_REPO:
        return
    os.chdir(tempfile.gettempdir())
    try:
        shutil.rmtree(DEMO_REPO,
                      onerror=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
    except Exception:
        print(f"   (résidus à supprimer manuellement : {DEMO_REPO})")


def main():
    print("s18 : isolation par worktree — démo non destructive, sans LLM")
    print(f"WORKDIR (figé à l'import de shared) : {WORKDIR}")

    # 1. La frontière de sécurité : valider le nom AVANT que git le voie.
    print("\n1. validate_worktree_name :")
    for name in ("auth", "../evil", "a b", ""):
        err = validate_worktree_name(name)
        print(f"   {name!r:10} → {err or 'OK'}")

    # 2. Tâche + worktree liés en un appel : create_worktree(name, task_id)
    # appelle bind_task_to_worktree après le succès git.
    t1 = create_task("s18-demo : refactor auth", "démo s18")
    print("\n2. " + create_worktree("auth", t1.id))
    print(f"   t1.worktree = {load_task(t1.id).worktree!r}, "
          f"status = {load_task(t1.id).status!r}")

    # 3. Liaison séparée : bind n'assigne PAS la tâche — elle reste pending,
    # revendicable par l'auto-claim de s17 (lier ≠ assigner).
    t2 = create_task("s18-demo : refactor ui", "démo s18")
    print("\n3. " + create_worktree("ui"))
    bind_task_to_worktree(t2.id, "ui")
    print(f"   t2.worktree = {load_task(t2.id).worktree!r}, "
          f"status = {load_task(t2.id).status!r}")

    # 4. Garde-fou : avec un fichier non commité, la suppression refuse par
    # défaut et propose les deux issues (discard_changes / keep_worktree).
    wt_auth = WORKTREES_DIR / "auth"
    if wt_auth.exists():
        (wt_auth / "wip.txt").write_text("travail en cours\n")
    print("\n4. remove sur worktree sale → " + remove_worktree("auth"))

    # 5. L'alternative : keep_worktree ne supprime rien, journalise la
    # décision et indique la branche wt/auth à examiner.
    print("5. " + keep_worktree("auth"))

    # 6. Suppressions : « ui » est propre → autorisée ; « auth » → forcée.
    print("6. " + remove_worktree("ui"))
    print("   " + remove_worktree("auth", discard_changes=True))

    # 7. Le journal d'audit, écrit uniquement après succès git réel.
    events = WORKTREES_DIR / "events.jsonl"
    if events.exists():
        print("\n7. journal .worktrees/events.jsonl :")
        for line in events.read_text().splitlines():
            print("   " + line)

    _cleanup()


if __name__ == "__main__":
    main()
