---
title: "s14 · Cron Scheduler"
session: 14
phase: "Tâches & temps"
fichier: "src/sessions/s14.py"
lignes: 125
tags: [cron, scheduler, threads, queue, durabilite]
prev: "s13-background-tasks"
next: "s15-agent-teams"
---

# s14 · Cron Scheduler

> **En une phrase** : un thread démon — démarré par [[shared-py]] dès l'import — évalue chaque seconde des expressions cron à 5 champs et pousse les jobs qui tirent dans `cron_queue` ; ce fichier vérifie que le thread tourne, valide des expressions, et fait tirer un one-shot sous nos yeux.

## Rôle dans le harness

Depuis [[s13-background-tasks]], l'agent sait travailler pendant qu'une commande lente tourne — mais chaque opération reste déclenchée par un humain. « Lance les tests tous les matins à 9h » exige un réveil-matin : le modèle producteur/file/consommateur du cron. Le *scheduler* (thread démon, tick 1 s, anti-double-tir par marqueur à la minute) fait tirer les jobs dont l'expression matche ; la file `cron_queue` découple le tir de la consommation ; et le consommateur — `agent_loop`, qui draine la file en tête de chaque tour — transforme le `prompt` du job en message user `[Scheduled]`. Le job ne contient pas une commande : il contient un **prompt**, et c'est le LLM qui décide quoi en faire.

Point structurant : le scheduler n'est pas démarré par ce fichier. [[shared-py]] amorce à l'import (l. 957–958) le rechargement des jobs durables (`.scheduled_tasks.json`) puis le thread `cron_scheduler_loop` — comme dans le capstone s20. `s14.py` le **vérifie** au démarrage au lieu d'en lancer un deuxième. « Durable » signifie seulement que la définition du job survit au redémarrage : si le processus est éteint à l'heure dite, rien ne tire.

## Ce que fait ce fichier

### pick() — lignes 30–31

Filtre `BUILTIN_TOOLS` par nom.

### Câblage module — lignes 34–41

`TOOL_NAMES = ("schedule_cron", "list_crons", "cancel_cron", "bash")` : les 3 outils cron plus `bash` (pour que les prompts planifiés puissent agir). `SYSTEM` (lignes 37–41) explique le format 5 champs, `recurring=false` pour les one-shots, `durable=true` pour la persistance, et le préfixe `[Scheduled]` des injections.

### scheduler_thread() — lignes 44–50

La vérification demandée par la session : retrouver le thread démarré par shared à l'import.

```python
def scheduler_thread():
    """Retrouve le thread cron_scheduler_loop démarré à l'import de shared
    (inspection de _target : suffisant pour une vérification de démo)."""
    for t in threading.enumerate():
        if getattr(t, "_target", None) is cron_scheduler_loop:
            return t
    return None
```

`Thread._target` est un attribut privé de CPython — acceptable pour un diagnostic de démo, pas pour de la production. Le `getattr` défensif évite tout plantage si l'implémentation change.

### show_validation() — lignes 53–61

Démo hors-ligne de `validate_cron` sur sept expressions : les valides (`0 9 * * *`, `*/5 * * * *`, le piège dom/dow `0 9 13 * 5` — « le 13 du mois OU le vendredi », sémantique Unix historique, `30 8-10 * * 1,3,5` avec plages et listes) et les invalides, dont les messages nomment le champ fautif (`minute: Value 61 out of bounds [0-59]`, `day-of-week: Value 7 out of bounds [0-6]`, `Expected 5 fields, got 3`).

### demo_one_shot() — lignes 64–86

Le tir en direct, sans LLM :

```python
    target = datetime.now() + timedelta(minutes=1)
    expr = f"{target.minute} {target.hour} * * *"
    job = schedule_job(expr, "Dire bonjour à l'utilisateur",
                       recurring=False, durable=False)
```

Un one-shot de session est calé sur la prochaine minute (le `isinstance(job, str)` ligne 71 gère le retour à double type de `schedule_job` : `CronJob` ou chaîne d'erreur). Puis la boucle d'attente appelle `consume_cron_queue()` chaque seconde : quand le thread de shared fait tirer le job (à la minute pile), le drainage le rapporte et on affiche son `prompt` — c'est exactement ce message que `agent_loop` injecterait comme `[Scheduled]`. `recurring=False` : le scheduler retire le job de `scheduled_jobs` aussitôt tiré. Ctrl-C annule proprement via `cancel_job`.

### main() — lignes 89–120

Au démarrage, `scheduler_thread()` confirme (ou non) que le thread de shared est vivant. Boucle interactive : `valide` (validation hors-ligne), `minute` (tir en direct), `jobs` (`run_list_crons` : étiquettes recurring/one-shot et durable/session), tout autre texte part dans `agent_loop` — qui draine lui-même `cron_queue` en tête de tour. `q` quitte.

## Ce qui vient de [[shared-py]]

Tout est importé explicitement (`from shared import (...)`, lignes 23–27) :

- `cron_scheduler_loop` — le thread démon (tick 1 s, marqueur `YYYY-MM-DD HH:MM` anti-double-tir, try/except par job), **déjà démarré à l'import** ; ce fichier ne fait que le retrouver.
- `validate_cron` — validation 5 champs avec bornes par champ et messages nommant le champ fautif.
- `schedule_job` / `cancel_job` — cycle de vie d'un `CronJob` (retour `CronJob | str`), persistance des durables dans `.scheduled_tasks.json`.
- `consume_cron_queue` — drainage atomique (copie + clear sous `cron_lock`).
- `run_list_crons` — le wrapper outil appelé par `jobs` (`run_schedule_cron`/`run_cancel_cron` arrivent par `BUILTIN_HANDLERS`, sans import direct) ; `agent_loop` (qui consomme la file en tête de tour), `BUILTIN_TOOLS`/`BUILTIN_HANDLERS`, `PROMPT`, `WORKDIR`, `print_turn_assistants`.

## Différences avec l'original learn-claude-code

- L'original (805 lignes) recopiait s12+s13 et embarquait son propre *queue processor* (`queue_processor_loop`, `run_agent_turn_locked`, `agent_lock`) pour réveiller l'agent inactif ; dans notre harness ce rôle revient à `cron_autorun_loop` de shared.py (utilisé par s20), et `s14.py` se concentre sur le chemin scheduler → file → injection.
- L'original démarrait le scheduler dans son propre module ; ici il est démarré une seule fois, à l'import de shared.py — `s14.py` le vérifie au lieu de le dupliquer (deux schedulers feraient tirer chaque job deux fois).
- La démo `minute` n'existait pas : l'original exigeait un tour LLM et une attente passive ; ici le tir est observable hors-ligne, à la minute près.
- Pièges du moteur portés tels quels : `*/N` matche `value % N == 0` (divergent du vrai cron pour les plages ne commençant pas à 0), pas de borne supérieure sur le pas, ids `cron_NNNNNN` aléatoires sans garantie d'unicité, sémantique OU dom/dow.

## Lancer la démo

```
python src/sessions/s14.py
```

Tout fonctionne sans clé API sauf les tours LLM : au lancement, `[ok]` confirme le thread de shared ; `valide` montre la validation ; `minute` programme un one-shot et on le regarde tirer (≤ 60 s) ; `jobs` liste l'état. Avec une clé, demander « rappelle-moi de faire une pause dans 2 minutes » : le modèle calcule l'expression, et le prompt `[Scheduled]` sera injecté au premier tour suivant le tir.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s13-background-tasks]]
- Session suivante : [[s15-agent-teams]]
- Sessions liées : [[s12-task-system]] (tâches durables, même philosophie disque), [[s17-autonomous-agents]] (l'agent qui agit sans humain), [[s20-comprehensive]] (où `cron_autorun_loop` rend l'agent long-running)
