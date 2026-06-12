---
title: "s18 · Isolation par worktree"
session: 18
phase: "Intégration & synthèse"
fichier: "src/sessions/s18.py"
lignes: 122
tags: [git-worktree, isolation, event-log, non-destructif]
prev: "s17-autonomous-agents"
next: "s19-mcp-plugin"
---

# s18 · Isolation par worktree

> **En une phrase** : chaque tâche peut être liée à un git worktree (répertoire + branche `wt/{nom}` dédiés) pour que deux agents ne s'écrasent plus leurs fichiers — la démo déroule tout le cycle de vie (validation du nom, create, bind, refus de suppression, keep, remove, journal d'audit) dans un dépôt git **jetable**, créé avant l'import de shared.

## Rôle dans le harness

En [[s17-autonomous-agents]], Alice et Bob travaillent dans le même répertoire : deux `write_file("config.py", ...)` et le travail de l'un écrase celui de l'autre. La réponse de s18 est `git worktree` : plusieurs répertoires de travail indépendants sur un même dépôt, une branche par worktree, et une liaison **minimale** avec le système de tâches — un champ `worktree` sur la `Task` (`bind_task_to_worktree`), qui ne change pas son statut : la tâche reste `pending`, c'est l'auto-claim de s17 qui la passera `in_progress` et basculera les outils fichiers du teammate dans le bon répertoire (le `wt_ctx` de `spawn_teammate_thread`). « Tasks own the goal, worktrees own the directory, bound by ID. »

Le cycle de vie est gardé à chaque étape : nom validé **avant** que git le voie (`validate_worktree_name`), suppression refusée par défaut s'il reste des changements non commités (`remove_worktree`), alternative explicite `keep_worktree`, et journal d'audit `events.jsonl` écrit uniquement après succès git réel (grâce au retour `(ok, output)` de `run_git`).

## Ce que fait ce fichier

### _setup_demo_repo() — lignes 30–47
La clé de la démo **non destructive** : crée un dépôt git jetable dans un répertoire temporaire — avec un commit initial, car `git worktree add ... HEAD` exige que HEAD pointe sur un commit — puis s'y place :

```python
        repo = tempfile.mkdtemp(prefix="s18_worktrees_")
        def git(*args):
            subprocess.run(["git", "-C", repo, *args], check=True,
                           capture_output=True, timeout=30)
        git("init", "-q")
        git("-c", "user.name=mekicode", "-c", "user.email=demo@mekicode",
            "commit", "--allow-empty", "-m", "init", "-q")
        os.chdir(repo)
```

En cas d'échec (git absent...), retourne `None` avec un message clair : la démo continuera dans le répertoire courant et affichera les erreurs propres de shared.

### DEMO_REPO / from shared import — lignes 50–54
L'ordre est **délibéré** et c'est la subtilité du fichier : `shared.WORKDIR = Path.cwd()` est figé au moment de l'import, et tous les répertoires de shared (`.tasks/`, `.worktrees/`, `.mailboxes/`, `.memory/`) sont créés à l'import. En se plaçant dans le dépôt jetable **avant** l'import de shared (`from shared import (...)`, l. 51–54, commenté `noqa: E402`), toute la démo — tâches comprises — vit dans le répertoire temporaire ; rien n'est touché dans le projet.

### _cleanup() — lignes 57–67
Sort du dépôt jetable puis le supprime ; les objets git sont en lecture seule sous Windows, d'où le `onerror` qui rétablit les droits à la volée (`os.chmod(p, 0o700)` puis retente). En dernier recours, affiche le chemin des résidus à supprimer manuellement.

### main() — lignes 70–117
Le cycle de vie, en sept temps numérotés comme à l'écran :

1. **Validation des noms** (l. 74–78) : `"auth"` → OK, `"../evil"`, `"a b"` et `""` → messages d'erreur. La frontière de sécurité est au niveau outil, avant git — les noms de worktrees deviennent des chemins.
2. **Tâche + worktree en un appel** (l. 80–85) : `create_worktree("auth", t1.id)` crée le répertoire et la branche `wt/auth` puis appelle `bind_task_to_worktree` ; le rechargement de t1 montre `worktree='auth'` et `status='pending'`.
3. **Liaison séparée** (l. 87–93) : `create_worktree("ui")` sans tâche, puis `bind_task_to_worktree(t2.id, "ui")` — lier ≠ assigner : t2 reste `pending`, revendicable par l'auto-claim de [[s17-autonomous-agents]].
4. **Le garde-fou** (l. 95–100) : un fichier `wip.txt` non commité est écrit dans le worktree, puis `remove_worktree("auth")` **refuse** et propose les deux issues (`discard_changes=true` ou `keep_worktree`).
5. **L'alternative** (l. 102–104) : `keep_worktree("auth")` ne supprime rien, journalise `keep` et indique la branche `wt/auth` à examiner.
6. **Suppressions** (l. 106–108) : `"ui"` est propre → suppression autorisée ; `"auth"` → forcée avec `discard_changes=True` (branche `wt/auth` supprimée aussi).
7. **Le journal** (l. 110–115) : affichage ligne à ligne de `.worktrees/events.jsonl` — on y lit `create` (×2), `keep`, `remove` (×2), chacun horodaté.

Puis `_cleanup()` (l. 117) efface le dépôt jetable.

## Ce qui vient de [[shared-py]]

- `WORKDIR` / `WORKTREES_DIR` — la racine figée à l'import et le répertoire `.worktrees/` (qui héberge aussi `events.jsonl`).
- `validate_worktree_name(name)` — rejet de vide, `.`, `..` et de tout caractère hors `[A-Za-z0-9._-]` (1–64).
- `create_worktree(name, task_id="")` — validation, vérification de la tâche, `git worktree add -b wt/{name} HEAD`, liaison, journal.
- `bind_task_to_worktree(task_id, worktree_name)` — écrit le champ `worktree`, le statut reste `pending`.
- `remove_worktree(name, discard_changes=False)` — refus par défaut si fichiers non commités/commits non poussés (ou si invérifiable).
- `keep_worktree(name)` — journalise la conservation, sans opération git.
- `create_task` / `load_task` — le système de tâches qui porte le champ `worktree` (et `run_git`/`log_event`, utilisés indirectement).

## Différences avec l'original learn-claude-code

- L'original `s18_worktree_isolation/code.py` (997 lignes) re-portait toute la pile (task system, protocole, teammates avec bascule `wt_ctx`, `TOOLS` à 17 entrées, REPL) ; ici 121 lignes — uniquement le cycle de vie worktree.
- **Démo non destructive** : l'original opérait dans le dépôt courant ; ici un dépôt git jetable est créé puis détruit, et le placement se fait *avant* l'import de shared (WORKDIR figé à l'import) — sans git utilisable, la démo affiche les messages d'erreur clairs de shared au lieu de planter.
- Le `create_worktree` de shared (hérité du s20 original) **vérifie l'existence de la tâche** avant de toucher à git — le crash `FileNotFoundError` documenté comme piège du s18 original ne peut plus arriver par cet appel (il reste possible en appelant `bind_task_to_worktree` directement avec un id inventé).
- La bascule de cwd des outils (`bash`/`read_file`/`write_file` à paramètre `cwd`, dict `wt_ctx` du thread teammate) n'est pas rejouée ici : elle vit dans `spawn_teammate_thread` de shared ; la démo montre la liaison côté **données** (champ `Task.worktree`).
- Pièges conservés tels quels dans shared et observables ici : `keep_worktree` ne vérifie pas l'existence du worktree, et la détection des commits non poussés (`git log @{push}..HEAD`) est inopérante sur les branches `wt/` fraîches (pas d'upstream) — seuls les fichiers non commités déclenchent réellement le refus.

## Lancer la démo

```
python src/sessions/s18.py
```

Sans appel LLM (l'import de shared exige `MODEL_ID` dans `.env`) ; nécessite `git` dans le PATH pour le scénario complet. On observe : le chemin du dépôt jetable, les quatre validations de noms, deux créations de worktrees (avec liaison de tâche), le refus de suppression sur worktree sale, le `keep`, les deux suppressions, puis le journal `events.jsonl` complet — et le nettoyage du répertoire temporaire.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s17-autonomous-agents]]
- Session suivante : [[s19-mcp-plugin]]
