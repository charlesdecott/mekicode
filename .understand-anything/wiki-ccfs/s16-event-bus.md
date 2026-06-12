---
title: "s16 · Event Bus & hooks"
session: 16
phase: "Durcissement production"
fichier: "inspiration/claude-code-from-scratch/s16_event_bus.py"
lignes: 301
tags: [event-bus, hooks, observer, pub-sub, lifecycle, observabilite, interception]
prev: "s15-permissions"
next: "s17-session-management"
---

# s16 · Event Bus & hooks

> **En une phrase** : un bus pub/sub minimal (`EventBus`) émet six événements de cycle de vie depuis la boucle d'agent, trois hooks intégrés (logger, stats, timer) les consomment, et un hook `pre_tool_use` peut renvoyer `{"block": True}` pour empêcher dynamiquement l'exécution d'un outil.

## Rôle dans le harness

Avec [[s15-permissions]], on sait *empêcher* ; on ne sait toujours pas *voir*. Combien de fois chaque outil a-t-il tourné ? Lequel est lent ? Que s'est-il passé à 14 h 32 ? Tant que la journalisation, les statistiques et le chronométrage sont des `print` dispersés dans la boucle, chaque nouveau besoin d'observabilité signifie rouvrir le code du moteur. La devise (ligne 6) : *« Every action fires an event; hooks let you observe and intercept »*.

La session installe une architecture **middleware** (docstring, lignes 7–20) : un bus d'événements central (pattern Observer) sur lequel on enregistre des handlers, et une boucle d'agent qui émet un événement à chaque moment critique — `session_start`, `agent_response`, `pre_tool_use`, `post_tool_use`, `tool_error`, `session_end` (lignes 22–28). Les logiques transverses (log, stats, timing) deviennent des fonctions **indépendantes et interchangeables**, découplées du moteur. Et le bus n'est pas qu'un miroir : les retours des hooks `pre_tool_use` sont collectés, et un `{"block": True}` suffit à intercepter l'exécution — l'observabilité débouche sur le contrôle.

L'analogie README (tableau Phase 4) : **« CC hooks system »**. Le vrai Claude Code expose exactement ce contrat dans `settings.json` : des hooks `PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`… qui sont des commandes externes dont le code de sortie ou le JSON de réponse peut bloquer ou réécrire l'action. Le repo jumeau learn-claude-code introduit lui aussi des hooks pre/post-tool-use dans sa session 4 ; la version ccfs généralise en bus multi-événements avec handlers multiples par événement.

C'est aussi la deuxième session de la phase (après [[s13-streaming]]) qui **ré-écrit la boucle au lieu d'appeler `stream_loop`** : il faut bien insérer les `bus.emit(...)` aux bons endroits, et `dispatch_tools` de core.py ne sait pas émettre d'événements entre la décision et l'exécution.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–29 | Shebang & docstring | Motto, 4 concepts (bus, lifecycle hooks, interception, découplage), liste des 6 événements |
| 31–36 | Imports stdlib | `os`, `sys`, `defaultdict`, `datetime`, `typing` |
| 38–47 | Imports core | `client`, `MODEL`, `EXTENDED_TOOLS`, `EXTENDED_DISPATCH`, `load_rules`, `check_permission`, `stream_loop` |
| 49–101 | **Le mécanisme** | Classe `EventBus` + instance globale `bus` |
| 103–155 | Hooks intégrés | `_LOG_FILE`, `hook_logger`, `hook_stats`, `hook_timer` |
| 158–161 | Câblage | Enregistrement des 3 hooks sur le bus |
| 164–259 | **Le mécanisme** | `agent_loop_with_hooks()` : la boucle instrumentée |
| 262–296 | REPL | `main()` |
| 299–301 | Point d'entrée | `if __name__ == "__main__"` |

## Constantes et configuration

- **`bus = EventBus()` (ligne 101)** : l'instance globale, partagée par tout le module — les hooks s'y enregistrent au chargement, la boucle y émet.
- **`_LOG_FILE = ".agent_events.log"` (ligne 106)** : le journal persistant, en append, dans le répertoire courant.
- **Le câblage (lignes 159–161)** :

```python
bus.on("pre_tool_use",  hook_logger).on("post_tool_use", hook_logger)
bus.on("session_start", hook_stats).on("post_tool_use", hook_stats).on("session_end", hook_stats)
bus.on("pre_tool_use",  hook_timer).on("post_tool_use", hook_timer)
```

Le chaînage fonctionne parce que `on()` renvoie `self`. On lit la matrice d'abonnements d'un coup d'œil : un même hook écoute plusieurs événements (le timer a besoin du pre *et* du post), un même événement nourrit plusieurs hooks (`post_tool_use` → logger, stats, timer).

## Les fonctions, une à une

### Classe `EventBus` — lignes 51–97

Un pub/sub de 25 lignes utiles.

#### `__init__()` — lignes 56–59

```python
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
```

`defaultdict(list)` : émettre un événement sans abonné itère sur une liste vide — aucun cas particulier à gérer, ni à l'enregistrement ni à l'émission.

#### `on(event, handler)` — lignes 61–73

Ajoute le handler à la liste de l'événement et **renvoie `self`** (ligne 73) pour permettre le chaînage vu plus haut. Pas de `off()` : on ne se désabonne jamais dans cette version.

#### `emit(event, **payload)` — lignes 75–97

```python
        results = []
        # Iterate through every handler registered for this specific event
        for handler in self._handlers[event]:
            try:
                # Execute the handler and capture its return value
                result = handler(event=event, **payload)
                if result is not None:
                    results.append(result)
            except Exception as e:
                # Catch and log hook errors so they don't crash the main agent
                print(f"\033[31m[EventBus] Hook error on '{event}': {e}\033[0m")
        return results
```

- **Ligne 91** : chaque handler reçoit `event=...` plus le payload en kwargs — c'est pourquoi tous les hooks ont la signature `(event: str, **payload)`. Un même handler peut donc écouter plusieurs événements et brancher sur `event`.
- **Lignes 92–93** : seuls les retours non-`None` sont collectés. Les hooks d'observation ne renvoient rien ; les hooks d'interception renvoient un dict. C'est ce qui permet à `pre_tool_use` de voter.
- **Lignes 94–96** : un hook qui plante est **attrapé et signalé en rouge, jamais propagé** — un bug d'observabilité ne doit pas tuer l'agent. Le revers : un hook de *sécurité* qui crashe est silencieusement neutralisé (voir Pièges).

### `hook_logger(event, **payload)` — lignes 108–117

Écrit une ligne horodatée par événement dans `.agent_events.log` :

```python
    log_line = f"[{timestamp}] EVENT={event} TOOL={tool_name}"
```

`payload.get("tool", "N/A")` : le hook est défensif, il ne suppose pas que le payload contient `tool`. Le fichier est ouvert/fermé à chaque événement (append) — simple et robuste, pas optimal.

### `hook_stats(event, **payload)` — lignes 120–136

Compte les usages d'outils. L'état vit dans un **attribut de fonction** :

```python
    if not hasattr(hook_stats, "_counts"):
        hook_stats._counts = defaultdict(int)
```

Astuce Python : `hook_stats._counts` persiste entre les appels sans variable globale ni classe. Le hook branche ensuite sur l'événement : `session_start` remet les compteurs à zéro, `post_tool_use` incrémente le compteur de l'outil, `session_end` imprime le bilan gris `[stats] Tool Usage: {...}`. Trois événements, un seul handler — la signature uniforme `(event, **payload)` rend ce multiplexage naturel.

### `hook_timer(event, **payload)` — lignes 139–155

Mesure la durée d'exécution de chaque outil en croisant deux événements : `pre_tool_use` enregistre `datetime.now()` dans `hook_timer._start_times[tool]`, `post_tool_use` fait `pop()` et calcule la durée.

```python
            duration = (datetime.now() - start_time).total_seconds()
            # Only alert the user if a command is significantly slow (> 5s)
            if duration > 5.0:
                print(f"\033[90m  [timer] Warning: '{tool_name}' was slow ({duration:.1f}s)\033[0m")
```

Seuil de signal : seules les exécutions > 5 s génèrent un avertissement — un hook bavard serait pire que pas de hook. La clé du dict est le *nom* de l'outil : deux exécutions simultanées du même outil se marcheraient dessus, ce qui n'arrive jamais ici (exécution séquentielle) mais deviendrait un bug réel avec [[s18-parallel-tools]].

### `agent_loop_with_hooks(messages)` — lignes 166–259

La boucle streaming de [[s13-streaming]], encadrée et instrumentée. La structure d'ensemble :

```python
    bus.emit("session_start")
    try:
        while True:
            ...
    finally:
        bus.emit("session_end")
```

- **Lignes 174 et 256–259** : `session_start` avant le premier tour, `session_end` dans un `finally` — le bilan des stats s'imprime **même sur Ctrl+C ou crash**. C'est ce qui rend les hooks fiables comme journal d'audit.
- **Lignes 189–202** : pendant le stream, les fragments sont à la fois imprimés *et* accumulés dans `text_chunks` ; après finalisation, si le tour contient du texte, `bus.emit("agent_response", text="".join(text_chunks))` livre la réponse complète aux abonnés (aucun par défaut — point d'extension prêt à l'emploi).

Le cœur de la session est l'exécution des outils, ré-écrite pour intercaler les événements :

```python
                # 1. Fire 'pre_tool_use' and check for blocks
                # Hooks can return {"block": True} to intercept execution
                pre_results = bus.emit("pre_tool_use", tool=block.name, input=block.input)
                is_blocked = any(r.get("block") for r in pre_results if isinstance(r, dict))

                if is_blocked:
                    output = "Error: Execution blocked by system security hook."
                else:
                    ...
                    handler = EXTENDED_DISPATCH.get(block.name)
                    try:
                        if handler:
                            output = handler(block.input)
                            # 2. Fire 'post_tool_use' on success
                            bus.emit("post_tool_use", tool=block.name, input=block.input, output=output)
                        else:
                            output = f"Error: Unknown tool '{block.name}'"
                    except Exception as e:
                        output = f"Execution Error: {e}"
                        # 3. Fire 'tool_error' on failure
                        bus.emit("tool_error", tool=block.name, error=str(e))
```

- **Lignes 219–220** : `emit` renvoie la liste des retours non-`None` des hooks ; `any(r.get("block") ...)` donne un **veto à n'importe quel hook** — un seul `{"block": True}` suffit. Le filtre `isinstance(r, dict)` ignore les retours d'un autre type. Aucun hook intégré ne bloque : le canal existe, libre à l'utilisateur d'y brancher par exemple `check_permission` (importé mais inutilisé — voir Pièges).
- **Ligne 223** : un blocage produit un message d'erreur renvoyé *au modèle* comme `tool_result` — même philosophie que [[s15-permissions]] : le refus est une donnée.
- **Lignes 230–241** : trois issues, trois événements — succès → `post_tool_use` (avec `output` dans le payload), exception → `tool_error`, outil inconnu → ni l'un ni l'autre. Noter que `post_tool_use` est émis *avant* l'affichage du snippet : les hooks voient la sortie brute complète.
- **Lignes 247–254** : collecte des `tool_result` et ré-injection en tour `user` — inchangé depuis [[s01-perception-action-loop]].

### `main()` — lignes 264–296

REPL standard : bannière annonçant les hooks actifs et le fichier de log (lignes 269–270), saisie cyan avec `try/except` → `sys.exit(0)`, sortie sur vide ou `q`/`exit`/`quit`, puis `agent_loop_with_hooks(history)`. À chaque requête utilisateur, la boucle ré-émet `session_start`/`session_end` : la « session » au sens du bus est *un tour de REPL*, pas le process entier.

### Point d'entrée — lignes 299–301

`if __name__ == "__main__": main()` — protection standard.

## Ce qui vient de [[core-py]]

Importés lignes 39–47 :

- **`client`**, **`MODEL`** — pour l'appel streaming direct (la boucle est ré-écrite ici).
- **`EXTENDED_TOOLS`** — les 6 schémas annoncés au modèle.
- **`EXTENDED_DISPATCH`** — la table nom → handler, consultée inline (ligne 230) au lieu de passer par `dispatch_tools`, pour pouvoir émettre les événements entre la consultation et l'exécution.
- **`load_rules`**, **`check_permission`** — importés mais **jamais appelés** dans ce fichier : une invitation à écrire soi-même un hook `pre_tool_use` qui rebranche la gouvernance de [[s15-permissions]] sur le bus.
- **`stream_loop`** — importé « pour référence » (commentaire ligne 46) et inutilisé : la session montre justement ce que `stream_loop` ne sait pas faire.

## Pièges et détails d'implémentation

- **`load_rules`, `check_permission` et `stream_loop` sont des imports morts** : s16 n'applique aucune règle YAML malgré ce que le docstring d'imports laisse croire. Le blocage par hook est un *canal* démontré, pas une politique active.
- **`emit` avale les exceptions des hooks** (lignes 94–96) : parfait pour l'observabilité, dangereux pour la sécurité — un hook de blocage qui lève une exception est neutralisé en silence (le veto n'est jamais vu) et l'outil s'exécute. Un hook de sécurité doit être infaillible ou le bus doit traiter ses erreurs comme un blocage (fail-closed).
- **La « session » du bus est un tour de REPL** : `session_start`/`session_end` encadrent chaque appel à `agent_loop_with_hooks`, donc les stats sont remises à zéro à chaque requête utilisateur — le bilan `[stats]` ne couvre jamais la conversation entière.
- **`hook_timer` indexe par nom d'outil** : deux `bash` concurrents partageraient la même clé. Inoffensif en séquentiel, bug garanti dès qu'on passe à l'exécution parallèle de [[s18-parallel-tools]].
- **Outil inconnu = angle mort des événements** : si le modèle hallucine un nom d'outil, ni `post_tool_use` ni `tool_error` ne sont émis — le logger n'a que le `pre_tool_use`. L'audit a un trou.
- **Prompt système local** : la boucle utilise `f"You are a coding agent at {os.getcwd()}."` codé en dur (ligne 184) au lieu du `DEFAULT_SYSTEM` de core.py — équivalent en pratique (moins « Act, don't explain »), mais c'est une duplication que le reste du repo évite.
- **Le log grossit indéfiniment** : `.agent_events.log` est ouvert en append à chaque événement, sans rotation ni nettoyage.

## Lancer la démo

```bash
python s16_event_bus.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou proxy LiteLLM). `config/permissions.yaml` n'est *pas* requis (importé, jamais lu). Au prompt `s16 >>`, demander quelques actions fichiers puis observer : les lignes `[timestamp] EVENT=pre_tool_use TOOL=bash` qui s'accumulent dans `.agent_events.log`, le bilan gris `[stats] Tool Usage: {'bash': 2, 'read': 1}` à la fin de chaque tour, et un éventuel `[timer] Warning` si une commande dépasse 5 s (essayer « lance sleep 6 »).

## Liens

- Socle : [[core-py]]
- Session précédente : [[s15-permissions]]
- Session suivante : [[s17-session-management]]
- Sessions liées : [[s15-permissions]] (gouvernance statique par règles, complémentaire du veto dynamique par hook), [[s13-streaming]] (la boucle streaming que s16 instrumente), [[s19-interrupts]] (autre forme d'interception du flux d'exécution)
