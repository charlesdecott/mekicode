---
title: "s13 · Tâches en arrière-plan"
session: 13
phase: "Tâches & temps"
fichier: "src/s13.py"
lignes: 119
tags: [background, threads, notifications, async, tool-use]
prev: "s12-task-system"
next: "s14-cron-scheduler"
---

# s13 · Tâches en arrière-plan

> **En une phrase** : les commandes bash lentes partent dans un thread démon, l'appel d'outil reçoit immédiatement un `tool_result` placeholder, et la vraie sortie revient plus tard comme bloc `<task_notification>` — démontré ici sans LLM grâce à un faux bloc `tool_use`.

## Rôle dans le harness

L'outil `bash` attend la fin de la commande : pendant un `pip install` de 10 minutes, l'agent ne fait rien — et le temps d'agent inactif, c'est du gaspillage. La solution est un double chemin d'exécution : les opérations lentes partent en thread démon, l'API reçoit tout de suite son `tool_result` placeholder (l'appariement `tool_use` ↔ `tool_result` exigé par l'API Messages est respecté), et la complétion arrive **plus tard** comme un événement indépendant — un bloc texte `<task_notification>`, jamais une réutilisation du `tool_use_id` d'origine.

Tout le mécanisme vit dans [[shared-py]], et `agent_loop` câble déjà les deux bouts : le détour arrière-plan au dispatch (`should_run_background` → `start_background_task`) et les **deux canaux de livraison** (`build_user_content` en fin de salve, `inject_background_notifications` en début de tour). Ce fichier rend le cycle observable hors-ligne en fabriquant le seul ingrédient qui vient normalement du modèle : le bloc `tool_use`.

## Ce que fait ce fichier

### pick() — lignes 28–29

Filtre `BUILTIN_TOOLS` par nom.

### Câblage module — lignes 32–38

`TOOL_NAMES = ("bash", "read_file", "write_file")` — aucun outil nouveau : c'est la *stratégie d'exécution* qui change, pas la palette. Le schéma de `bash` dans `BUILTIN_TOOLS` expose déjà `run_in_background: boolean`. `SYSTEM` (lignes 35–38) explique au modèle le contrat placeholder/notification.

### DemoBlock — lignes 41–51

Le stand-in d'un bloc `tool_use` du SDK :

```python
class DemoBlock:
    """Stand-in minimal d'un bloc tool_use du SDK (type/name/input/id) :
    juste ce qu'il faut pour piloter start_background_task sans appel LLM."""
    _seq = 0

    def __init__(self, command: str):
        DemoBlock._seq += 1
        self.type = "tool_use"
        self.name = "bash"
        self.input = {"command": command, "run_in_background": True}
        self.id = f"demo_bg_{DemoBlock._seq:04d}"
```

`start_background_task` ne lit que `block.name`, `block.input` et `block.id` — quatre attributs suffisent pour le piloter sans LLM. `run_in_background: True` reflète la demande explicite qu'un modèle ferait.

### show_heuristic() — lignes 54–67

Démo hors-ligne de la décision sync/async : cinq commandes passent par `should_run_background` et `is_slow_operation`. On voit l'heuristique mots-clés matcher `pip install requests`, `npm run build`, `python -m pytest -q` — mais aussi son faux positif assumé : `cat latest.log` part en arrière-plan parce qu'il contient « test ». La dernière ligne montre la hiérarchie : `run_in_background=true` explicite l'emporte, même sur `echo vite`.

### demo_background() — lignes 70–89

Le cycle complet sans LLM :

```python
    cmd = 'python -c "import time; time.sleep(2); print(\'fini\')"'
    bg_id = start_background_task(DemoBlock(cmd), HANDLERS)
```

Une commande de ~2 s part en worker démon ; `start_background_task` retourne immédiatement `bg_id` (le placeholder que recevrait le modèle). Puis la boucle de polling (lignes 78–83) appelle `inject_background_notifications(history)` toutes les 0,5 s : dès que le worker a déposé son résultat, un message user contenant le bloc `<task_notification>` (avec `task_id`, `status`, `command`, `summary`) apparaît en fin d'historique et est affiché. Le `history.pop()` final (ligne 89) retire ce message de démo pour ne pas laisser un user orphelin dans l'historique envoyé au LLM aux tours suivants.

### main() — lignes 92–114

Boucle interactive : `demo` (cycle hors-ligne), `heuristic` (décision sync/async), tout autre texte part dans `agent_loop` avec le pool figé — où le dispatch arrière-plan et les deux canaux de notification jouent pour de vrai. `q` quitte.

## Ce qui vient de [[shared-py]]

Tout est importé explicitement (`from shared import (...)`, lignes 21–25) :

- `is_slow_operation` / `should_run_background` — l'heuristique mots-clés et la hiérarchie de décision (demande du modèle d'abord).
- `start_background_task(block, handlers)` — worker démon, enregistrement avant démarrage du thread, `PostToolUse` déclenché quand même, résultat déposé sous `background_lock`.
- `collect_background_results` — drainage en blocs `<task_notification>` (non importé : appelé indirectement, via le canal d'injection).
- `inject_background_notifications(messages)` — le second canal de livraison, en début de tour, utilisé directement par la démo.
- `agent_loop` — qui câble détour arrière-plan + les deux canaux ; `BUILTIN_TOOLS`/`BUILTIN_HANDLERS`, `WORKDIR`, `PROMPT`, `print_turn_assistants`.

## Différences avec l'original learn-claude-code

- L'original (479 lignes) recopiait tout s12 + s10 et réécrivait `agent_loop` ; ici 118 lignes, dont la moitié pour les démos hors-ligne.
- `start_background_task` de shared.py prend la table `handlers` en paramètre (au lieu d'une globale `TOOL_HANDLERS`) et déclenche le hook `PostToolUse` même en arrière-plan — deux généralisations absentes de l'original.
- L'original ne livrait les notifications qu'en fin de salve d'outils (un modèle qui répondait en texte pur les attendait au tour suivant) ; shared.py a un second canal `inject_background_notifications` en **début** de tour, que la démo exploite.
- L'original exigeait un tour LLM pour observer le mécanisme ; `DemoBlock` rend le cycle placeholder → worker → notification reproductible hors-ligne et en ~2 secondes.
- Piège conservé tel quel : le résumé de notification est tronqué à 200 caractères et la sortie complète est perdue (`pop` des registres) ; le timeout de 120 s de `run_bash` s'applique aussi en arrière-plan.

## Lancer la démo

```
python src/s13.py
```

`demo` et `heuristic` fonctionnent sans clé API. `demo` montre en direct : `[background] bg_0001: ...` (le worker part), le placeholder immédiat, puis ~2 s plus tard la `<task_notification>` injectée comme message user. Avec une clé, demander par exemple « lance `pip install requests` puis lis README.md pendant que ça tourne » : le placeholder et la notification s'enchaînent dans le même tour.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s12-task-system]]
- Session suivante : [[s14-cron-scheduler]]
- Sessions liées : [[s02-tool-use]] (le contrat tool_use/tool_result que les notifications contournent proprement), [[s06-subagent]] (autre forme de travail délégué), [[s17-autonomous-agents]] (agents longue durée bâtis sur ces briques)
