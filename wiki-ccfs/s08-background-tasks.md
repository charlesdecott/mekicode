---
title: "s08 · Tâches en arrière-plan"
session: 08
phase: "Async & multi-agents"
fichier: "inspiration/claude-code-from-scratch/s08_background_tasks.py"
lignes: 236
tags: [background, threads, daemon, queue, notifications, injection]
prev: "s07-task-system"
next: "s09-agent-teams"
---

# s08 · Tâches en arrière-plan

> **En une phrase** : le nouvel outil `bash_background` lance la commande dans un thread daemon et rend la main immédiatement ; le résultat remonte par une `queue.Queue` thread-safe et est injecté dans la conversation comme un message `user`, déclenchant un « auto-turn » du modèle.

## Rôle dans le harness

Jusqu'ici, chaque appel d'outil est **bloquant** : quand le modèle demande `bash` pour lancer une suite de tests de 5 minutes, tout le harness attend — pas de lecture de fichiers, pas de planification, rien. La devise de la session le dit : *« Run slow operations in the background; the agent keeps thinking »*. C'est l'ouverture de la phase 3 du README, *« Breaking the single-agent ceiling »* : avant de multiplier les agents (s09–s12), on apprend d'abord à ne plus bloquer l'agent unique.

La solution tient en trois pièces. Un **thread daemon** exécute la commande pendant que la boucle principale continue ; une **file de notifications** (`queue.Queue`, la seule structure de la stdlib pensée pour passer des données entre threads sans verrou explicite) transporte le résultat du thread vers la boucle ; et une **injection d'événement** transforme ce résultat en faux message utilisateur ajouté à l'historique — le modèle le découvre au tour suivant comme s'il venait de l'extérieur.

Le tableau « Claude Code Analog » du README rattache cette session à la **file asynchrone `h2A`** du vrai Claude Code : un canal qui permet d'injecter des événements (sorties de tâches de fond, steering de l'utilisateur — repris côté entrée dans [[s19-interrupts]]) dans la conversation entre deux tours, sans casser l'alternance assistant/user exigée par l'API. Le vrai CC expose la même capacité via le paramètre `run_in_background` de son outil Bash et les notifications de complétion. Dans le projet jumeau learn-claude-code, le mécanisme équivalent est la session s13 (background tasks), construite sur le même trio thread + queue + injection.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–27 | Shebang & docstring | Devise, les 4 concepts (threads, queue, injection, feedback non bloquant) |
| 29–35 | Imports stdlib | `threading`, `queue`, `subprocess`, `sys`, typing |
| 37–45 | Imports core | 6 symboles du socle (voir « Ce qui vient de core-py ») |
| 47–60 | Configuration | `_NOTIFY_QUEUE`, `SYSTEM` spécialisé |
| 62–113 | **Nouveau** | `run_bash_background()` + son worker interne `_worker_logic()` |
| 116–135 | **Nouveau** | `_drain_notifications()` : vidange de la file → messages `user` |
| 138–169 | Schémas & dispatch | `BG_TOOLS` (+1 outil), `BG_DISPATCH` |
| 171–195 | **Nouveau** | `agent_loop_with_bg()` : tour standard + auto-turns de notification |
| 198–231 | Point d'entrée | `main()` : REPL classique |
| 234–236 | Lancement | `if __name__ == "__main__"` |

## Constantes et configuration

- **`_NOTIFY_QUEUE` (ligne 51)** : `queue.Queue()` globale — le pont thread-safe entre les workers et la boucle principale. Les threads y déposent (`put`), la boucle y puise (`get_nowait`). Préfixe `_` : détail interne, pas une API de la session.
- **`SYSTEM` (lignes 54–60)** : prompt système spécialisé qui enseigne le **contrat asynchrone** au modèle : *« Use bash_background for slow operations like tests, builds, or long scripts. This tool returns immediately. The result of the command will be provided to you automatically via a notification in a later turn. While waiting, you should continue working on other available tasks. »* Sans cette dernière phrase, le modèle aurait tendance à boucler en demandant « est-ce fini ? » au lieu d'avancer.
- **`BG_TOOLS` (lignes 141–160)** : `EXTENDED_TOOLS + [bash_background]`. Le schéma n'exige que `command` ; `label` est optionnel (*« A short identifier for the notification »*) — c'est la clé de corrélation entre le lancement et la notification.
- **`BG_DISPATCH` (lignes 163–169)** : étend `EXTENDED_DISPATCH` par dépliage `**` — le motif d'extension canonique du repo, une entrée ajoutée, rien de réécrit :

```python
BG_DISPATCH: Dict[str, Any] = {
    **EXTENDED_DISPATCH, # Include standard bash, read, etc.
    "bash_background": lambda inp: run_bash_background(
        inp["command"], 
        inp.get("label", "")
    ),
}
```

À noter ligne 167 : le défaut de `label` est `""` (et non `None`) — ça fonctionne quand même, voir les pièges.

## Les fonctions, une à une

### `run_bash_background(command, label=None)` — lignes 64–113

L'outil lui-même. Il ne fait que trois choses : choisir un label, démarrer un thread, et **retourner immédiatement** un accusé de réception.

```python
    # Default label to a snippet of the command if none provided
    task_label = label or command[:40]
    ...
    # Initialize the thread. 'daemon=True' ensures the thread dies if the main app exits.
    worker_thread = threading.Thread(target=_worker_logic, daemon=True)
    worker_thread.start()
    
    return f"Background task started: '{task_label}'. You will be notified when it finishes."
```

- **Ligne 79** : `label or command[:40]` — fallback sur les 40 premiers caractères de la commande. Le `or` traite à la fois `None` et la chaîne vide.
- **Lignes 110–111** : `daemon=True` signifie que le thread ne retient pas le processus : si l'utilisateur quitte le REPL, les tâches en cours meurent avec lui (cf. pièges).
- **Ligne 113** : le retour est la valeur du `tool_result` envoyé au modèle. La formulation (*« You will be notified »*) répète le contrat du prompt système — redondance volontaire : c'est dans le résultat d'outil que le modèle lit l'état du monde.

### `_worker_logic()` (interne à `run_bash_background`) — lignes 81–107

La closure exécutée dans le thread. Elle capture `command` et `task_label` de la fonction englobante.

```python
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True,
                text=True, 
                timeout=300, 
                cwd=os.getcwd()
            )
            # Capture and truncate output to avoid context window flooding (2k chars)
            output = (result.stdout + result.stderr).strip()[:2000] or "(no output)"
            status = "completed"
        ...
        # Format the notification for the agent and put it in the thread-safe queue
        notification = f"[Background task '{task_label}' {status}]\n{output}"
        _NOTIFY_QUEUE.put(notification)
```

- **Lignes 87–94** : à l'intérieur du thread, l'exécution redevient **synchrone** (`subprocess.run` bloquant) — c'est tout l'intérêt : la complexité asynchrone est confinée au harness, le code d'exécution reste trivial. Timeout de **300 s** (contre 120 s pour le `run_bash` du socle) : on backgrounde précisément les opérations longues.
- **Ligne 96** : troncature agressive à **2 000 caractères** (contre 50 000 pour le bash synchrone). Une notification arrive sans avoir été demandée à ce moment-là ; elle ne doit pas engloutir le contexte.
- **Lignes 98–103** : trois statuts possibles — `completed`, `timed out`, `failed` — tous convertis en texte. Comme partout dans le repo, une erreur d'outil est une donnée pour le modèle, jamais une exception qui remonte (d'autant qu'ici elle tuerait silencieusement le thread).
- **Lignes 106–107** : le format `[Background task 'X' completed]\n<sortie>` est auto-descriptif — le modèle peut corréler avec le label retourné au lancement. `Queue.put()` est thread-safe par construction, aucun verrou à écrire.

### `_drain_notifications()` — lignes 116–135

Vide la file et convertit chaque notification en bloc message prêt à entrer dans l'historique.

```python
    notifs = []
    # Exhaust the queue completely before returning
    while not _NOTIFY_QUEUE.empty():
        try:
            # Get notification without blocking
            msg = _NOTIFY_QUEUE.get_nowait()
            print(f"\033[90m  [bg] notification received: {msg[:80]}...\033[0m")
            notifs.append({"role": "user", "content": msg})
        except queue.Empty:
            break
    return notifs
```

- **Lignes 125 et 128** : `empty()` puis `get_nowait()` sous `try/except queue.Empty` — ceinture et bretelles. `empty()` n'est qu'indicatif en contexte multi-thread (un autre consommateur pourrait vider la file entre le test et le `get`) ; le `except` ferme la fenêtre de course. Ici il n'y a qu'un consommateur, mais le motif est le bon réflexe.
- **Ligne 132** : le point conceptuel de la session — la notification devient un message **`role: "user"`**. Impossible d'utiliser un `tool_result` : l'appel `bash_background` a déjà reçu sa réponse (« Background task started ») au tour du lancement. Le seul canal légal pour de l'information nouvelle non sollicitée, c'est un tour utilisateur — exactement la technique des system-reminders et notifications du vrai Claude Code.

### `agent_loop_with_bg(messages)` — lignes 173–195

L'orchestration : un tour standard, puis livraison des notifications en attente.

```python
    # 1. Execute the standard autonomous turn (Thinking -> Acting -> Thinking)
    stream_loop(messages, BG_TOOLS, BG_DISPATCH, system=SYSTEM)
    
    # 2. Check if any background tasks finished while the agent was working/waiting
    pending_notifications = _drain_notifications()
    
    # 3. If notifications exist, append them and force an immediate follow-up turn
    for notif in pending_notifications:
        messages.append(notif)
        print("\033[94m  [auto-turn] Processing background notification...\033[0m")
        # Recursively call the loop to process the new information
        stream_loop(messages, BG_TOOLS, BG_DISPATCH, system=SYSTEM)
```

- **Ligne 185** : le tour autonome complet de [[core-py]] (`stream_loop` boucle tant que `stop_reason == "tool_use"`). Pendant ce temps, les workers tournent en parallèle et peuvent alimenter la file.
- **Ligne 188** : la vidange n'a lieu **qu'après** la fin du tour — l'injection se fait à la frontière des tours, jamais au milieu (on ne peut pas insérer un message `user` entre un `tool_use` et son `tool_result`).
- **Lignes 191–195** : chaque notification produit son propre message **et son propre tour complet** (`stream_loop` rappelé) — l'« auto-turn » : le modèle réagit au résultat sans que l'utilisateur ait rien tapé. Malgré le commentaire ligne 194 (*« Recursively call »*), c'est une simple itération : les notifications arrivées *pendant* ces tours de rattrapage ne seront drainées qu'au prochain passage.

### `main()` — lignes 200–231

REPL standard du repo : bannière grise (ligne 205), prompt cyan `s08 >> ` (ligne 214), sortie sur `q`/`exit`/`quit`/ligne vide (lignes 221–222) ou `Ctrl+C` via `sys.exit(0)` (ligne 218). La seule différence avec les sessions précédentes : la ligne 228 appelle `agent_loop_with_bg(history)` au lieu de `stream_loop` directement.

## Ce qui vient de [[core-py]]

Import unique en tête de fichier (lignes 38–45) :

- **`EXTENDED_TOOLS`** — les 6 schémas standards (bash, read, write, grep, glob, revert), base de `BG_TOOLS` (ligne 141).
- **`EXTENDED_DISPATCH`** — la table de handlers correspondante, dépliée dans `BG_DISPATCH` (ligne 164).
- **`stream_loop`** — le moteur de tour autonome (streaming + dispatch + rebouclage), appelé lignes 185 et 195.
- **`client`, `MODEL`, `dispatch_tools`** — importés mais **jamais utilisés directement** dans s08 : `stream_loop` s'en sert en interne, côté core. L'import est un en-tête uniforme copié entre sessions, pas un besoin réel (voir pièges).

## Pièges et détails d'implémentation

- **`bash_background` ne vérifie pas `_ALWAYS_BLOCK`** : contrairement au `run_bash` du socle, le worker (lignes 87–94) exécute la commande sans passer par la liste noire de core.py — `sudo` ou `rm -rf /` passent en arrière-plan sans contrôle. Le durcissement par règles déclaratives arrive dans [[s15-permissions]].
- **Livraison décalée d'un tour entier** : la vidange a lieu *après* `stream_loop` (ligne 188), pas avant. Une tâche qui se termine pendant que l'utilisateur tape sa question suivante n'est pas vue par le modèle pendant le tour qui répond à cette question — elle n'est livrée qu'après. Drainer aussi *avant* le tour corrigerait ça.
- **`daemon=True` = résultats perdus à la sortie** : quitter le REPL tue les workers en plein vol ; ni trace, ni notification. Acceptable pour une démo, rédhibitoire en production (s22 passe sur Redis, durable et inter-processus).
- **Troncature asymétrique** : 2 000 caractères pour une sortie background contre 50 000 en synchrone — une suite de tests verbeuse perd l'essentiel de son log ; seuls le début et le statut survivent.
- **`inp.get("label", "")` fonctionne par accident** : le défaut est `""`, pas `None`, mais la ligne 79 (`label or command[:40]`) traite les deux pareil parce que la chaîne vide est falsy.
- **Un appel API par notification** : trois tâches finies = trois auto-turns complets (lignes 191–195) au lieu d'un seul message groupé — simple, mais coûteux en tokens et en latence.
- **Imports décoratifs** : `client`, `MODEL`, `dispatch_tools` (lignes 39–43) ne servent à rien ici — ne pas chercher de logique cachée, c'est le bloc d'import standard du repo.

## Lancer la démo

```bash
cd inspiration/claude-code-from-scratch
python s08_background_tasks.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou `ANTHROPIC_BASE_URL` pointant vers un proxy LiteLLM, cf. README). Aucune dépendance au-delà de `requirements.txt`.

Essayer : `lance "sleep 8 && echo TESTS OK" en arrière-plan, puis liste les fichiers Python du dossier`. On observe : le modèle appelle `bash_background` (`[bg] started: ...` en gris), enchaîne *immédiatement* sur `glob` sans attendre, termine son tour ; quelques secondes plus tard `[bg] notification received: ...` puis `[auto-turn] Processing background notification...` en bleu — le modèle commente le résultat des tests sans qu'on ait rien tapé.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s07-task-system]]
- Session suivante : [[s09-agent-teams]]
- Sessions liées : [[s18-parallel-tools]] (l'autre réponse à la lenteur : paralléliser les outils d'un même tour avec asyncio), [[s19-interrupts]] (la même injection à la frontière des tours, côté entrées utilisateur — l'analogue `h2A` complet), [[s15-permissions]] (bouche le trou de la liste noire contournée)
