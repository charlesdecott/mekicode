---
title: "s11 · Récupération d'erreurs"
session: 11
phase: "Contexte & mémoire"
fichier: "src/sessions/s11.py"
lignes: 135
tags: [erreurs, retry, backoff, fallback-model, resilience]
prev: "s10-system-prompt"
next: "s12-task-system"
---

# s11 · Récupération d'erreurs

> **En une phrase** : une mini-boucle d'agent où l'appel LLM nu est blindé par les trois chemins de récupération de [[shared-py]] — `with_retry` pour les transitoires (429/529 + bascule de modèle), `reactive_compact` pour le dépassement de contexte, escalade de `max_tokens` pour la sortie tronquée.

## Rôle dans le harness

En production, les erreurs API sont la norme, pas l'exception : un 529 « overloaded », un 429 « rate limit », un contexte devenu trop long, une réponse coupée en pleine phrase. Sans récupération, chacun de ces incidents tue l'agent. La session s11 montre comment envelopper *un seul point* du harness — l'appel `client.messages.create` — pour absorber les trois classes d'échec, chacune avec sa stratégie propre et ses garde-fous (drapeaux à usage unique, plafonds de retries).

Toute la mécanique (`RecoveryState`, `retry_delay`, `with_retry`, `is_prompt_too_long_error`, `reactive_compact`) vit dans [[shared-py]] ; ce fichier écrit volontairement sa **propre** boucle `resilient_turn` au lieu d'appeler `agent_loop`, pour que le câblage des trois chemins reste visible sur une page — c'est exactement ce que fait `agent_loop` en interne, en condensé.

## Ce que fait ce fichier

### pick() — lignes 27–28

Le helper standard des sessions : filtre `BUILTIN_TOOLS` par nom pour construire un sous-ensemble d'outils.

```python
def pick(*names):
    return [t for t in BUILTIN_TOOLS if t["name"] in names]
```

### Câblage module — lignes 31–35

`TOOL_NAMES = ("bash", "read_file", "write_file")` : les 3 outils de base, comme dans l'original. `TOOLS`/`HANDLERS` en sont les sous-ensembles (schémas et table miroir), `SYSTEM` est un prompt système figé — pas d'assemblage vivant ici, le sujet est la résilience.

### show_backoff() — lignes 38–45

Démo hors-ligne : imprime trois tirages de `retry_delay(attempt)` pour chaque tentative de 0 à `MAX_RETRIES - 1`. On voit le doublement exponentiel (base 500 ms, plafond 32 s) et le jitter de 0–25 % qui rend chaque tirage différent — la parade au *thundering herd* (des clients qui retentent tous au même instant).

### show_detector() — lignes 48–60

Démo hors-ligne : passe quatre exceptions synthétiques à `is_prompt_too_long_error` et affiche le verdict. Seules les formulations « prompt too long » / `context_length_exceeded` matchent ; les 429/529 sont classés « autre erreur » — eux relèvent de `with_retry`, pas de la compaction.

### resilient_turn() — lignes 63–105

Le cœur du fichier : un tour d'agent complet avec les trois chemins câblés autour de l'appel LLM.

```python
            response = with_retry(
                lambda mt=max_tokens: client.messages.create(
                    model=state.current_model, system=SYSTEM,
                    messages=history, tools=TOOLS, max_tokens=mt),
                state)
```

- **Chemin transitoire** (lignes 73–77) : l'appel passe par `with_retry` avec un `RecoveryState` créé en début de tour (ligne 67). Le lambda fige `max_tokens` par argument par défaut mais relit `state.current_model` à chaque tentative : la bascule `FALLBACK_MODEL` opérée par `with_retry` prend effet **immédiatement**, dès la tentative suivante — l'original learn souffrait d'une bascule à retardement (le modèle était lui aussi figé en argument par défaut).
- **Chemin contexte** (lignes 78–83) : si `is_prompt_too_long_error(e)` et que le drapeau `has_attempted_reactive_compact` est encore baissé, `history[:] = reactive_compact(history)` puis `continue`. Une seule chance : recompacter un historique déjà compacté ne le rendrait pas plus petit.
- **Irrécupérable** (lignes 84–86) : toute autre exception est consignée comme message assistant `[Error] ...` — visible dans l'historique, le modèle pourra s'y adapter au tour suivant.
- **Chemin max_tokens** (lignes 87–92) : à la première troncature, la sortie tronquée est **jetée** (pas d'append) et la même requête repart avec `ESCALATED_MAX_TOKENS` ; le drapeau `has_escalated` interdit une deuxième escalade.
- **Tour normal** (lignes 93–105) : append de la réponse, sortie si `has_tool_use` est faux, sinon exécution des outils via `call_tool_handler` et renvoi des `tool_result`.

### main() — lignes 108–130

Boucle interactive : `backoff` et `detect` lancent les démos hors-ligne (aucun appel API), tout autre texte devient un tour LLM via `resilient_turn`, dont les textes assistants sont rendus par `print_turn_assistants` (avec `turn_start` noté avant le tour : un tour avec continuation ou erreur produit plusieurs messages assistant). `q` quitte.

## Ce qui vient de [[shared-py]]

Tout est importé explicitement (`from shared import (...)`, lignes 19–24) :

- `RecoveryState` — l'état du tour : `has_escalated`, `recovery_count`, `consecutive_529`, `has_attempted_reactive_compact`, `current_model`.
- `with_retry(fn, state)` — jusqu'à `MAX_RETRIES` tentatives ; 429 → backoff, 529 → backoff + bascule `FALLBACK_MODEL` après `MAX_CONSECUTIVE_529` ; le reste est relancé tel quel.
- `retry_delay(attempt)` — backoff exponentiel plafonné 32 s + jitter 0–25 %.
- `is_prompt_too_long_error(e)` / `reactive_compact(messages)` — détection du dépassement de contexte et compaction d'urgence (résumé LLM sous try/except avec repli).
- `client`, `DEFAULT_MAX_TOKENS`, `ESCALATED_MAX_TOKENS`, `MAX_RETRIES`, `BASE_DELAY_MS`, `WORKDIR`, `PROMPT` — config et console.
- `BUILTIN_TOOLS` / `BUILTIN_HANDLERS`, `call_tool_handler`, `has_tool_use`, `print_turn_assistants` — la plomberie d'exécution d'outils et de rendu.

## Différences avec l'original learn-claude-code

- L'original (366 lignes) redéfinissait tout : outils, assemblage de prompt s10, constantes, `RecoveryState`, `with_retry`… Ici, 134 lignes : seul le câblage et les démos hors-ligne restent.
- Le `reactive_compact` de l'original gardait bêtement les 5 derniers messages (au risque de casser une paire tool_use/tool_result) ; la version de shared.py résume par LLM avec texte de repli, comme en s08/s09.
- La bascule `FALLBACK_MODEL` de l'original ne prenait effet qu'à l'itération suivante de la boucle externe (modèle figé en argument par défaut du lambda) ; ici le lambda relit `state.current_model` à chaque tentative.
- Le prompt de continuation (`CONTINUATION_PROMPT`, jusqu'à `MAX_RECOVERY_RETRIES` fois) n'est pas recâblé dans `resilient_turn` — il est démontré par `agent_loop` de shared.py, que les sessions s12+ utilisent.
- Constantes recalibrées dans shared.py : `MAX_RETRIES` 10 → 3, `ESCALATED_MAX_TOKENS` 64000 → 16000, `MAX_CONSECUTIVE_529` 3 → 2.

## Lancer la démo

```
python src/sessions/s11.py
```

`backoff` et `detect` fonctionnent sans clé API (table des délais, classification d'erreurs). Avec une clé (`MODEL_ID` dans `.env`), tout autre texte lance un tour LLM résilient : on observe les retries `[429]`/`[529]` en jaune et la bascule de modèle en rouge si l'API tousse.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s10-system-prompt]]
- Session suivante : [[s12-task-system]]
- Sessions liées : [[s08-context-compact]] (la compaction préventive dont `reactive_compact` est le filet d'urgence), [[s01-agent-loop]] (la boucle nue que s11 blinde)
